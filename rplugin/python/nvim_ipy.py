from __future__ import print_function, division
from functools import partial, wraps
from collections import deque
import os, sys
import json
import re
import neovim
import IPython
from IPython.kernel import KernelClient, KernelManager
from IPython.core.application import BaseIPythonApplication
from IPython.consoleapp import IPythonConsoleApp
from IPython.qt.console.ansi_code_processor import AnsiCodeProcessor

import greenlet

# from http://serverfault.com/questions/71285/in-centos-4-4-how-can-i-strip-escape-sequences-from-a-text-file
strip_ansi = re.compile('\x1B\[([0-9]{1,2}(;[0-9]{1,2})?)?[m|K]')

py3_hack = False

import logging
logger = logging.getLogger(__name__)
error, debug, info, warn = (logger.error, logger.debug, logger.info, logger.warn,)
if 'NVIM_IPY_DEBUG_FILE' in os.environ:
    logfile = os.environ['NVIM_IPY_DEBUG_FILE'].strip()
    logger.addHandler(logging.FileHandler(logfile, 'w'))
    logger.level = logging.DEBUG

class RedirectingKernelManager(KernelManager):
    def _launch_kernel(self, cmd, **b):
        # stdout is used to communicate with nvim, redirect it somewhere else
        self._null = open("/dev/null","w",0)
        b['stdout'] = self._null.fileno()
        b['stderr'] = self._null.fileno()
        if py3_hack: cmd[0] = "python3"
        return super(RedirectingKernelManager, self)._launch_kernel(cmd, **b)

class IPythonVimApp(BaseIPythonApplication, IPythonConsoleApp):
    # don't use blocking client; we override call_handlers below
    kernel_client_class = KernelClient
    kernel_manager_class = RedirectingKernelManager
    aliases = IPythonConsoleApp.aliases #this the way?
    flags = IPythonConsoleApp.flags
    def init_kernel_client(self):
        #TODO: cleanup this (by subclassing kernel_clint or something)
        if self.kernel_manager is not None:
            self.kernel_client = self.kernel_manager.client()
        else:
            self.kernel_client = self.kernel_client_class(
                                ip=self.ip,
                                transport=self.transport,
                                shell_port=self.shell_port,
                                iopub_port=self.iopub_port,
                                stdin_port=self.stdin_port,
                                hb_port=self.hb_port,
                                connection_file=self.connection_file,
                                parent=self,
            )
        self.kernel_client.shell_channel.call_handlers = self.target.on_shell_msg
        self.kernel_client.iopub_channel.call_handlers = self.target.on_iopub_msg
        self.kernel_client.stdin_channel.call_handlers = self.target.on_stdin_msg
        self.kernel_client.hb_channel.call_handlers = self.target.on_hb_msg
        self.kernel_client.start_channels()

    def initialize(self, target, argv):
        self.target = target
        super(IPythonVimApp, self).initialize(argv)
        IPythonConsoleApp.initialize(self, argv)

# this is not strictly neccesary, as nvim client lib already wraps
# every notification in its own greenlet, but this ensures the code still
# works even if nvim_client stops using greenlets
def ipy_async(f):
    @wraps(f)
    def new_f(*a,**b):
        gr = greenlet.greenlet(f)
        return gr.switch(*a, **b)
    return new_f

class Threadsafe(object):
    def __init__(self, wraps):
        self.wraps = wraps

    def __getattr__(self, name):
        return partial(self.wraps.vim.session.threadsafe_call, getattr(self.wraps, name))

class MsgHandler(object):
    def __init__(self, handler):
        self.msgs = deque()
        self.handler = handler
        self.is_active = False

    def __call__(self, msg):
        self.msgs.append(msg)
        if not self.is_active:
            self.is_active = True
            while self.msgs:
                self.handler(self.msgs.popleft())
            self.is_active = False

@neovim.plugin
class IPythonPlugin(object):
    def __init__(self, vim):
        self.vim = vim
        self.buf = None
        self.has_connection = False

        self.pending_shell_msgs = {}

        # make sure one message is handled at a time
        self.on_iopub_msg = MsgHandler(self._on_iopub_msg)


    def configure(self):
        #FIXME: rethink the entire configuration interface thing
        self.max_in = self.vim.vars.get("ipy_truncate_input", 0)
        if self.vim.vars.get("ipy_shortprompt", False):
            self.prompt_in  = "{}: "
            self.prompt_out = "{}: "
        else:
            self.prompt_in  = "In[{}]: "
            self.prompt_out = "Out[{}]: "

    def create_outbuf(self):
        vim = self.vim
        if self.buf is not None:
            return
        w0 = vim.current.window
        vim.command(":new")
        buf = vim.current.buffer
        buf.options["swapfile"] = False
        buf.options["buftype"] = "nofile"
        buf.name = "[ipython]"
        vim.current.window = w0
        self.buf = buf
        self.hl_handler = AnsiCodeProcessor()
        self.hl_handler.bold_text_enabled = True

    def add_highlight(self, grp, row, start=1, end=-1):
        self.vim.session.request('buffer_add_highlight', self.buf, 1, grp, row, start, end)


    # FIXME: encoding
    def append_outbuf(self, data):
        self.hl_handler.reset_sgr()
        data = strip_ansi.sub('', data)
        lineno = len(self.buf)
        lastline = self.buf[-1]

        txt = lastline + data
        self.buf[-1:] = txt.split("\n") # not splitlines
        for w in self.vim.windows:
            if w.buffer == self.buf:
                w.cursor = [len(self.buf), int(1e9)]
        return lineno

    # FIXME: encoding
    def append_outbuf_esc(self, data):
        lineno = len(self.buf)
        lastline = self.buf[-1]
        colpos = len(lastline)+1

        textdata = strip_ansi.sub('', data)
        txt = lastline + textdata
        self.buf[-1:] = txt.split("\n") # not splitlines
        for i,line in enumerate(data.split("\n")):
            for chunk in self.hl_handler.split_string(line):
                l = len(chunk)
                bold = self.hl_handler.bold or self.hl_handler.intensity > 0
                color = self.hl_handler.foreground_color
                if color and color > 8: color = None

                if color is not None:
                    name = "IPyFg{}".format(color)
                    if bold: name += "Bold"
                elif bold:
                    name = "IPyBold"
                else:
                    name = None
                if name:
                    self.add_highlight(name, lineno+i, colpos, colpos+l-1)
                colpos += l
            colpos = 1

        for w in self.vim.windows:
            if w.buffer == self.buf:
                w.cursor = [len(self.buf), int(1e9)]
        return lineno

    # TODO: should cleanly support reconnecting ( cleaning up previous connection)
    @ipy_async
    def connect(self, argv):
        global py3_hack
        self.configure()
        vim = self.vim
        self.create_outbuf()

        # hack for IPython2.x
        if len(argv) >= 2 and argv[:2] == ["--kernel", "python3"]:
            del argv[:2]
            py3_hack = True
        else:
            py3_hack = False

        self.ip_app = IPythonVimApp()
        # messages will be recieved in IPython's event loop threads
        # so use the threadsafe self
        self.ip_app.initialize(Threadsafe(self), argv)
        self.kc = self.ip_app.kernel_client
        self.km = self.ip_app.kernel_manager
        self.sc = self.kc.shell_channel
        self.has_connection = True

        reply = self.waitfor(self.sc.kernel_info())
        c = reply['content']
        lang = c['language']
        try:
            ipy_version = c['ipython_version']
        except KeyError:
            ipy_version = IPython.version_info
        vdesc = '.'.join(str(i) for i in ipy_version[:3])
        if ipy_version[3] != '':
            vdesc += '-' + ipy_version[3]
        banner = [
                "nvim-ipy: Jupyter shell for Neovim",
                "IPython {}".format(vdesc),
                "language: {} {}".format(lang, '.'.join(str(i) for i in c['language_version'])),
                "",
                ]
        self.buf[:0] = banner
        for i in range(len(banner)):
            self.add_highlight('Comment', i+1)

        w0 = vim.current.window
        if vim.current.buffer != self.buf:
            for w in vim.windows:
                if w.buffer == self.buf:
                    vim.current.window = w
                    break
            else:
                return #reopen window?
        #vim.command("set ft={}".format(lang))

        vim.current.window = w0

    def disp_status(self, status):
        self.vim.vars['ipy_status'] = status

    def handle(self, msg_id, handler):
        self.pending_shell_msgs[msg_id] = handler

    def waitfor(self, msg_id, retval=None):
        #FIXME: add some kind of timeout
        gr = greenlet.getcurrent()
        self.handle(msg_id, gr)
        return gr.parent.switch(retval)

    def ignore(self, msg_id):
        self.handle(msg_id, None)

    @neovim.function("IPyConnect")
    def ipy_connect(self, args):
        self.connect(args)

    @neovim.function("IPyRun")
    @ipy_async
    def ipy_run(self, args):
        (code,) = args
        if self.km and not self.km.is_alive():
            choice = int(self.vim.eval("confirm('Kernel died. Restart?', '&Yes\n&No')"))
            if choice == 1:
                self.km.restart_kernel(True)
            return

        reply = self.waitfor(self.sc.execute(code))
        content = reply['content']
        payload = content['payload']
        for p in payload:
            if p.get("source") == "page":
                # TODO: if this is long, open separate window
                self.append_outbuf(p['text'])

    @neovim.function("IPyComplete")
    @ipy_async
    def ipy_complete(self,args):
        line = self.vim.current.line
        #FIXME: (upstream) this sometimes get wrong if 
        #completi:g just after entering insert mode:
        #pos = self.vim.current.buffer.mark(".")[1]+1
        pos = int(self.vim.eval("col('.')"))-1

        reply = self.waitfor(self.sc.complete('', line, pos))
        content = reply["content"]
        #TODO: check if position is still valid
        start = pos-len(content['matched_text'])+1
        matches = json.dumps(content['matches'])
        self.vim.command("call complete({}, {})".format(start,matches))

    @neovim.function("IPyObjInfo")
    @ipy_async
    def on_ipy_objinfo(self, args):
        word, level = args
        reply = self.waitfor(self.sc.object_info(word, level))

        c = reply['content']
        if not c['found']:
            self.append_outbuf("not found: {}\n".format(o['name']))
            return
        self.append_outbuf("\n")
        for field in ['name','namespace','type_name','base_class','length','string_form',
            'file','definition','source', 'init_definition', 'docstring']:
            if c.get(field) is None:
                continue
            sep = '\n' if c[field].count('\n') else ' '
            #TODO: option for separate doc buffer
            line = self.append_outbuf_esc('{}:{}{}\n'.format(field,sep,c[field].rstrip()))
            self.add_highlight('Statement', line, 1, len(field)+2)

    @neovim.function("IPyInterrupt")
    def on_ipy_interrupt(self, args):
        self.km.interrupt_kernel()

    @neovim.function("IPyTerminate")
    def on_ipy_terminate(self, args):
        self.km.shutdown_kernel()

    def _on_iopub_msg(self, m):
        #FIXME: figure out the smoothest way to to matchaddpos
        # (from a different window), or just use concealends
        t = m['header'].get('msg_type',None)
        c = m['content']

        debug('iopub %s: %r', t, c)

        if t == 'status':
            status = c['execution_state']
            self.disp_status(status)
        elif t == 'pyin':
            prompt = self.prompt_in.format(c['execution_count'])
            code = c['code'].rstrip().split('\n')
            if self.max_in and len(code) > self.max_in:
                code = code[:self.max_in] + ['.....']
            sep = '\n'+' '*len(prompt)
            line = self.append_outbuf('\n{}{}\n'.format(prompt, sep.join(code)))
            self.add_highlight('IPyIn', line+1, 1, len(prompt))
        elif t == 'pyout':
            no = c['execution_count']
            res = c['data']['text/plain']
            prompt = self.prompt_out.format(c['execution_count'])
            # not 100% reliable, append_outbuf should do all highlighting
            line = self.append_outbuf_esc((self.prompt_out + '{}\n').format(no, res.rstrip()))
            self.add_highlight('IPyOut', line, 1, len(prompt))
        elif t == 'pyerr':
            #TODO: this should be made language specific
            # as the amt of info in 'traceback' differs
            self.append_outbuf_esc('\n'.join(c['traceback']) + '\n')
        elif t == 'stream':
            #perhaps distinguish stderr using gutter marks?
            self.append_outbuf_esc(c['data'])
        elif t == 'display_data':
            d = c['data']['text/plain']
            self.append_outbuf_esc(d + '\n')


    def on_shell_msg(self, m):
        debug('shell %s: %r', m['msg_type'], m['content'])
        msg_id = m['parent_header']['msg_id']
        try:
            handler = self.pending_shell_msgs.pop(msg_id)
        except KeyError:
            debug('unexpected shell msg: %r', m)
            return
        if isinstance(handler, greenlet.greenlet):
            handler.parent = greenlet.getcurrent()
            handler.switch(m)
        elif handler is not None:
            handler(m)

    #this gets called when heartbeat is lost
    def on_hb_msg(self, time_since):
        self.disp_status("DEAD")

    def on_stdin_msg(self, msg):
        self.vim.vars['ipy_prompt'] = "(IPy) " + msg["content"]["prompt"]
        self.kc.input(self.vim.eval("input(g:ipy_prompt)"))
