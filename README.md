# nvim-ipy
This is a IPython/Jupyter front-end for Neovim, partially based on [ivanov/vim-ipython](https://github.com/ivanov/vim-ipython), but refactored for nvim's plugin architechture and improved async event handling. IPython 3.x or later is required. It uses python2 per default; see below for notes on using python3. It has full support for non-python kernels.

## Features
The main feature (relative most similar vim plugins):

- IT HAS ASYNC

This means it has better support for long-running commands that continously produce output, for instance this silly example:

    from time import sleep
    for i in range(10):
        sleep(0.5)
        print(i)

It still lack some features from vim-ipython, like displaying docs in a separate window.

## Connecting/starting kernel
`:IPython <args>` is interpreted just like the command line `ipython console <args>`, for instance:

Action                  | command
----------------------- | -------
Start new python kernel |  `:IPython` <br> `:IPython3` (for python3 kernel)
Connect to existing kernel | `:IPython --existing`
Start kernel in different language | `:IPython --kernel julia-0.4`

Kernelspec can be used to launch a python3 kernel from nvim-ipy when running in the python2 host (default), the same way as from the Jupyter console and notebook. Use `:IPython --kernel python3` or the `:IPython3` shortcut. You might need to execute

    ipython3 kernelspec install-self --user

on beforehand for this to work.  I have tested that this plugin also supports IJulia and IHaskell, but ideally it should work with any Jupyter kernel.

This plugin runs in the python2 host by default, but it is also compatible with the python3 plugin host. There isn't yet any nice interface to configure this, but for now you can either move `rplugin/python/nvim_ipy.py` to `rplugin/python3/nvim_ipy.py` (and then reexecute `:UpdateRemotePlugins`) or alternatively,
edit `~/.nvim/.nvimrc-rplugin~` manually and change the first `'python'` to `'python3'` on the line

    call remote#host#RegisterPlugin('python', '.../nvim-ipy/rplugin/python/nvim_ipy.py', [

(_after_ executing `:UpdateRemotePlugins`) This will launch a python3 kernel per default.

## Keybindings

When kernel is running, following bindings can be used:

Generic                   | default     | Action
------------------------- | ----------  | ------
`<Plug>(IPy-Run)`         | `<F5>`      | Excecute current line or visual selection
`<Plug>(IPy-Complete)`    | `<C-F>`     | (insert mode) Kernel code completion
`<Plug>(IPy-WordObjInfo)` | `<leader>?` | Inspect variable under the cursor
`<Plug>(IPy-Interrupt)`   | `<F8>`      | Send interrupt to kernel
`<Plug>(IPy-Terminate)`   |             | Terminate kernel

### But... The default bindings suck!
Yes, they exist mainly to quickly test this plugin. Add

    let g:nvim_ipy_perform_mappings = 0

To your nvimrc and map to the generic bindings. For instance:

    map <silent> <c-s>   <Plug>(IPy-Run)

## Options?

Are not abound. You can get slimmer input/output prompts by setting

    let g:ipy_shortprompt = 1

I also happen to dislike echoing long multi-line inputs in the output window.

    let g:ipy_truncate_input = 3

will limit the displayed input to the first 3 lines.

## Exported vimscript functions
Most useful is `IPyRun("string of code")` which can be called to programmatically execute any code. This is useful to bind common commands to a key.

`IPyConnect(args...)` can likewise be used to connect with vimscript generated arguments.
