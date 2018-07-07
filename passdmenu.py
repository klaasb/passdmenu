#!/usr/bin/env python3

import sys
import os
import os.path as path
import subprocess
import shutil
import argparse
import re


XCLIP = shutil.which('xclip')
XDOTOOL = shutil.which('xdotool')
DMENU = shutil.which('dmenu')
PASS = shutil.which('pass')
STORE = os.getenv('PASSWORD_STORE_DIR',
                  path.normpath(path.expanduser('~/.password-store')))
XSEL_PRIMARY = "primary"


def get_xselection(selection):
    if not selection:  # empty or None
        return None
    for option in [XSEL_PRIMARY, "secondary", "clipboard"]:
        if option[:len(selection)] == selection:
            return option
    return None


def check_output(args):
    output = subprocess.check_output(args)
    output = output.decode('utf-8').split('\n')
    return output


def dmenu(choices, args=[], path=DMENU):
    """
    Displays a menu with the given choices by executing dmenu
    with the provided list of arguments. Returns the selected choice
    or None if the menu was aborted.
    """
    dmenu = subprocess.Popen([path] + args,
                             stdin=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    choice_lines = '\n'.join(map(str, choices))
    choice, errors = dmenu.communicate(choice_lines.encode('utf-8'))
    if dmenu.returncode not in [0, 1] \
       or (dmenu.returncode == 1 and len(errors) != 0):
        print("'{} {}' returned {} and error:\n{}"
              .format(path, ' '.join(args), dmenu.returncode,
                      errors.decode('utf-8')),
              file=sys.stderr)
        sys.exit(1)
    choice = choice.decode('utf-8').rstrip()
    return choice if choice in choices else None


def collect_choices(store, regex=None):
    choices = []
    for dirpath, dirs, files in os.walk(store, followlinks=True):
        dirsubpath = dirpath[len(store):].lstrip('/')
        for f in files:
            if f.endswith('.gpg'):
                full_path = os.path.join(dirsubpath, f[:-4])
                if not regex or re.match(regex, full_path):
                    choices += [full_path]
    return choices


def xdotool(entries, press_return, delay=None, window_id=None):
    getwin = ""
    always_opts = "--clearmodifiers"
    if delay:
        always_opts += " --delay '{}'".format(delay)
    if not window_id:
        getwin = "getactivewindow\n"
    else:
        always_opts += " --window {}".format(window_id)

    commands = [c for e in entries[:-1] for c in (
        "type {} '{}'".format(always_opts, e),
        "key {} Tab".format(always_opts))]
    if len(entries) > 0:
        commands += ["type {} '{}'".format(always_opts, entries[-1])]
    if press_return:
        commands += ["key {} Return".format(always_opts)]
    for command in commands:
        input_text = "{}{}".format(getwin, command)
        subprocess.check_output([XDOTOOL, "-"],
                                input=input_text,
                                universal_newlines=True)


def get_pass_output(gpg_file, path=PASS, store=STORE):
    environ = os.environ.copy()
    environ["PASSWORD_STORE_DIR"] = store
    passp = subprocess.Popen([path, gpg_file], env=environ,
                             stderr=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    output, err = passp.communicate()
    if passp.returncode != 0:
        print("pass returned {} and error:\n{}".format(
            passp.returncode, err.decode('utf-8')), file=sys.stderr)
        sys.exit(1)
    return output.decode('utf-8').split('\n')

def get_user_second_line(pass_output):
    userline = pass_output[1].split()
    user = None

    if len(userline) > 1:
        # assume the first 'word' after some prefix is the username
        # TODO any better, reasonable assumption for lines
        # with more 'words'?
        user = userline[1]
    elif len(userline) == 1:
        # assume the user has no 'User: ' prefix or similar
        user = userline[0]

    return user

def get_user_by_pattern(pass_output, user_pattern):
    for line in pass_output[1:]:
        match = re.match(user_pattern, line)
        if match and  len(match.groups()) == 1:
            return match.group(1)

    return None

def get_user_from_filename(gpg_file):
    return gpg_file.split('/')[-1]

def get_user_pw(pass_output, user_pattern, gpg_file):
    password = None
    if len(pass_output) > 0:
        password = pass_output[0]
    user = None
    if len(pass_output) > 1:
        if user_pattern == 'filename':
            user = get_user_from_filename(gpg_file)
        elif user_pattern == '':
            user = get_user_second_line(pass_output) or \
                   get_user_from_filename(gpg_file)
        elif user_pattern is not None:
            user = get_user_by_pattern(pass_output, user_pattern)

    return user, password


def main():
    desc = ("A dmenu frontend to pass."
            " All passed arguments not listed below, are passed to dmenu."
            " If you need to pass arguments to dmenu which are in conflict"
            " with the options below, place them after --."
            " Requires xclip in default 'copy' mode.")
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-c', '--copy', dest='copy', action='store_true',
                        help=('Use xclip to copy the username and/or '
                              'password into the primary/specified '
                              'xselection(s). This is the default mode.'))
    parser.add_argument('-t', '--type', dest='autotype', action='store_true',
                        help=('Use xdotool to type the username and/or '
                              'password into the currently active window.'))
    parser.add_argument('-r', '--return', dest='press_return',
                        action='store_true',
                        help='Presses "Return" after typing. Forces --type.')
    parser.add_argument('-u', '--user', dest="get_user", nargs='?', const='',
                        default=None,
                        help='Copy/type the username, possibly search by given '
                        'python regex pattern that must include a group (the '
                        'user part). Example pattern: \'^user: (.*)\'. '
                        'If second line of gpg file is blank or the argument '
                        '\'filename\' is given then gpg filename is used as '
                        'username.')
    parser.add_argument('-P', '--pw', dest="get_pass", action='store_true',
                        help=('Copy/type the password. Default, use -u -P to '
                              'copy both username and password.'))
    parser.add_argument('-s', '--store', dest="store", default=STORE,
                        help=('The path to the pass password store. '
                              'Defaults to ~/.password-store'))
    parser.add_argument('-d', '--delay', dest="xdo_delay", default=None,
                        help=('The delay between keystrokes. '
                              'Defaults to xdotool\'s default.'))
    parser.add_argument('-f', '--filter', dest="filter", default=None,
                        help='A regular expression to filter pass filenames.')
    parser.add_argument('-B', '--pass', dest="pass_bin", default=PASS,
                        help=('The path to the pass binary. '
                              'Cannot find a default path to pass, '
                              'you must provide this option.'
                              if PASS is None else 'Defaults to ' + PASS))
    parser.add_argument('-D', '--dmenu', dest="dmenu_bin", default=DMENU,
                        help=('The path to the dmenu binary. '
                              'Cannot find a default path to dmenu, '
                              'you must provide this option.'
                              if DMENU is None else 'Defaults to ' + DMENU))
    parser.add_argument('-x', '--xsel', dest="xsel", default=XSEL_PRIMARY,
                        help=('The X selections into which to copy the '
                              'username/password. Possible values are comma-'
                              'separated lists of prefixes of: '
                              'primary, secondary, clipboard. E.g. -x p,s,c. '
                              'Defaults to primary.'))
    parser.add_argument('-e', '--execute', dest="execute", default=None,
                        help=('The path to a command to execute. The whole '
                              'content of the decrypted gpg file from pass '
                              'is provided to it on standard input. The full '
                              'password name (within the store) is provided as '
                              'first parameter. Arguments -s and -f are '
                              'forwarded as parameters.'
                              'The command is executed in addition to and '
                              'after specified -t, -c options are handled.'))

    split_args = [[]]
    curr_args = split_args[0]
    for arg in sys.argv[1:]:
        if arg == "--":
            split_args.append([])
            curr_args = split_args[-1]
            continue
        curr_args.append(arg)

    args, unknown_args = parser.parse_known_args(args=split_args[0])

    if args.get_user is None and not args.get_pass:
        args.get_pass = True

    if args.press_return:
        args.autotype = True

    if not args.autotype and not args.execute:
        args.copy = True

    error = False
    if args.pass_bin is None:
        print("You need to provide a path to pass. See -h for more.",
              file=sys.stderr)
        error = True

    if args.dmenu_bin is None:
        print("You need to provide a path to dmenu. See -h for more.",
              file=sys.stderr)
        error = True

    prompt = ""
    if args.autotype:
        if XDOTOOL is None:
            print("You need to install xdotool.", file=sys.stderr)
            error = True
        if args.press_return:
            prompt = "enter"
        else:
            prompt = "type"

    if args.copy:
        if XCLIP is None:
            print("You need to install xclip.", file=sys.stderr)
            error = True
        prompt += ("," if prompt != "" else "") + "copy"

    if args.execute:
        if shutil.which(args.execute) is None:
            print("The command to execute is not executable or does not exist.")
            error = True
        else:
            prompt += (("," if prompt != "" else "") +
                       os.path.basename(args.execute))

    # make sure the password store exists
    if not os.path.isdir(args.store):
        print("The password store location, " + args.store +
              ", does not exist.", file=sys.stderr)
        error = True
    if shutil.which(args.pass_bin) is None:
        print("The pass binary, {}, does not exist or is not executable."
              .format(args.pass_bin), file=sys.stderr)
        error = True

    if error:
        sys.exit(1)

    dmenu_opts = ["-p", prompt] + unknown_args
    # XXX for now, append all split off argument lists to dmenu's args
    for arg_list in split_args[1:]:
        dmenu_opts += arg_list

    # get active window id now, it may change between dmenu/rofi and xdotool
    window_id = None
    if args.autotype:
        window_id = check_output([XDOTOOL, 'getactivewindow'])[0]

    choices = collect_choices(args.store, args.filter)
    choice = dmenu(choices, dmenu_opts, args.dmenu_bin)
    # Check if user aborted
    if choice is None:
        sys.exit(0)
    pass_output = get_pass_output(choice, args.pass_bin, args.store)
    user, pw = get_user_pw(pass_output, args.get_user, choice)

    info = []
    if user is not None:
        info += [user]
    if args.get_pass and pw is not None:
        info += [pw]

    clip = '\n'.join(info).encode('utf-8')

    if args.autotype:
        xdotool(info, args.press_return, args.xdo_delay, window_id)

    if args.copy:
        for selection in args.xsel.split(','):
            xsel_arg = get_xselection(selection)
            if xsel_arg:
                xclip = subprocess.Popen([XCLIP, "-selection", xsel_arg],
                                         stdin=subprocess.PIPE)
                xclip.communicate(clip)
            else:
                print("Warning: Invalid xselection argument: {}."
                      .format(selection), file=sys.stderr)
    if args.execute:
        cmd_with_args=([args.execute, choice, "-s", args.store] +
                       (["-f", args.filter] if args.filter else []))
        cmd = subprocess.Popen(cmd_with_args, stdin=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        output, _ = cmd.communicate('\n'.join(pass_output).encode('utf-8'))
        if cmd.returncode != 0:
            print("Command {} returned {} and output:\n{}".format(
                  args.execute, cmd.returncode, output.decode('utf-8')),
                  file=sys.stderr)
            sys.exit(1)
        else:
            print(output.decode('utf-8'), end='')


if __name__ == "__main__":
    main()
