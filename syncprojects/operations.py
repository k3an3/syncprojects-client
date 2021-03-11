import logging
import logging
import subprocess
from concurrent.futures.thread import ThreadPoolExecutor
from os import listdir
from os.path import join, isfile, islink, isdir

from progress.bar import IncrementalBar

from syncprojects import config as config
from syncprojects.utils import print_hr, current_user, format_time, validate_changelog, prompt_to_exit, handle_link, \
    get_patched_progress

logger = logging.getLogger('syncprojects.operations')


def copy(dir_name, src, dst, update=True):
    copy_tree(join(src, dir_name), join(dst, dir_name), update=update)


def changelog(directory):
    from syncprojects.storage import appdata
    changelog_file = join(appdata['source'], directory, "changelog.txt")
    if not isfile(changelog_file):
        logger.info("Creating changelog...")
        divider = print_hr("*", config.CHANGELOG_HEADER_WIDTH)
        changelog_header = divider + "\n*{}*\n".format(
            ("CHANGELOG: " + directory).center(config.CHANGELOG_HEADER_WIDTH - 2)) + divider
        with open(changelog_file, "w") as f:
            f.write(changelog_header)
    print("Add a summary of the changes you made to {}, then save and close Notepad.".format(directory))
    user = current_user()
    header = "\n\n-- {}: {} --\n".format(user, format_time())
    header += "=" * (len(header) - 3) + "\n\n"
    with open(changelog_file, "r+") as f:
        lines = f.readlines()
        lines.insert(3, header)
        f.seek(0)
        f.writelines(lines)
    subprocess.run([config.NOTEPAD, changelog_file])
    while err := validate_changelog(changelog_file):
        logger.warning("Error! Improper formatting in changelog. Please correct it:\n")
        logger.warning(err)
        subprocess.run([config.NOTEPAD, changelog_file])


def handle_new_song(song_name, remote_hs):
    if song_name not in remote_hs.content:
        for song in remote_hs.content.keys():
            if song_name.lower() == song.lower():
                logger.error(
                    f"\nERROR: Your song is named \"{song_name}\", but a similarly named song \"{song}\" "
                    f"already exists remotely. Please check your spelling/capitalization and try again.")
                # TODO
                # unlock(project, api_client)
                prompt_to_exit()


progress = get_patched_progress()


def copy_tree(src, dst, preserve_mode=1, preserve_times=1,
              preserve_symlinks=0, update=0, verbose=1, dry_run=0,
              progress=True, executor=None, single_depth=False):
    from distutils.file_util import copy_file
    from distutils.dir_util import mkpath

    if not executor:
        executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)

    names = listdir(src)

    if not dry_run:
        mkpath(dst, verbose=verbose)

    outputs = []
    if progress:
        bar = IncrementalBar("Copying", max=len(names))
    for n in names:
        src_name = join(src, n)
        dst_name = join(dst, n)

        if progress:
            bar.next()
        if n.startswith('.nfs'):
            # skip NFS rename files
            continue

        if preserve_symlinks and islink(src_name):
            outputs.append(executor.submit(handle_link, src_name, dst_name, verbose, dry_run))

        elif isdir(src_name) and not single_depth:
            outputs.append(
                executor.submit(
                    copy_tree, src_name, dst_name, preserve_mode,
                    preserve_times, preserve_symlinks, update,
                    verbose=verbose, dry_run=dry_run, progress=False, executor=executor))
        else:
            executor.submit(
                copy_file, src_name, dst_name, preserve_mode,
                preserve_times, update, verbose=verbose,
                dry_run=dry_run)
            outputs.append(dst_name)
    if progress:
        bar.finish()
    return outputs
