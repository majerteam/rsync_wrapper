#!/usr/bin/python3

"""
Run rsync backup and log all data.

Config file mandatory.

Places for config file
-----------------------

File must be named run_backup.rc an can exist in any xdg config dirs,
or in the user's home

Example config file
-----------------------

[main_backup]
host=192.168.12.26
src_dir=/dir/to/sync/
dst_dir=/mirror/of/dir
logbase=/place/where/i/log
"""


import collections
import configparser
import datetime
import logging
import os
import smtplib
import subprocess
import sys

from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart


class BackupException(Exception):
    pass


class ConfigException(BackupException):
    pass


StreamHandler = getattr(logging, 'StreamHandler', None)
if not StreamHandler:
    # depends on Python version?
    import logging.handlers
    StreamHandler = logging.handlers.StreamHandler


# holds config

Context = collections.namedtuple(
    'BackupContext',
    (
        'host',
        'src_dir',
        'dst_dir',
        'logfile',
        'mail',
        'log_out_fd',
        'log_err_fd',
        'log_ret_fd',
    )
)


MailConfig = collections.namedtuple(
    'MailConfig',
    (
        'mailto',
        'mailfrom',
        'smtp',
    )
)


def backup(context, logger):
    """
    Actually run rsync
    """
    command = [
        'rsync',
        '-avz',
        '--delete',
        '{context.host}:{context.src_dir}'.format(context=context),
        '{context.dst_dir}'.format(context=context),
    ]

    logger.info("running command {0}".format(' '.join(command)))
    for desc, fname in (
        ("python log", context.logfile),
        ("stdout", context.log_out_fd.name),
        ("stderr", context.log_err_fd.name),
        ("return code", context.log_ret_fd.name),
            ):
        logger.info("{0} goes to {1}".format(desc, fname))

    process = subprocess.Popen(
        command,
        stdout=context.log_out_fd,
        stderr=context.log_err_fd,
    )
    process.wait()
    returncode = process.returncode

    if returncode == 0:
        logfn = logger.info
    else:
        logfn = logger.critical

    context.log_ret_fd.write('{0}\n'.format(process.returncode))
    logfn('{0[0]} exited with status {1}'.format(command, returncode))

    for descr in (context.log_out_fd, context.log_err_fd, context.log_ret_fd):
        descr.close()


def _config_file():
    """
    Locate the config file or raises ConfigException
    """
    config_fname = 'run_backup.rc'
    candidates = []
    try:
        import xdg.BaseDirectory
        for directory in xdg.BaseDirectory.xdg_config_dirs:
            candidate = os.path.join(directory, config_fname)
            candidates.append(candidate)
            if os.path.exists(candidate):
                return candidate
    except ImportError:
        pass
    candidate = os.path.join(os.environ['HOME'], config_fname)
    if os.path.exists(candidate):
        return candidate
    candidates.append(candidate)
    raise ConfigException("No config file. Places examined: {}".format(
        ', '.join(candidates)
    ))


def context(section_name='main_backup'):
    """Read data, clean it up a bit
    """

    config = configparser.ConfigParser()
    config_fname = _config_file()
    config.read(config_fname)
    if section_name not in config:
        raise ConfigException("Need a '{}' section in {}".format(
            section_name, config_fname
        ))
    host = config[section_name]['host']
    src_dir = config[section_name]['src_dir']
    dst_dir = config[section_name]['dst_dir']
    logbase = config[section_name]['logbase']

    mailto = config[section_name].get('mailto', '')
    if mailto:
        try:
            mailcfg = config['mail']
        except KeyError:
            raise ConfigException(
                "mailto not null in section {0}, but no section 'mail'".format(
                    section_name
                )
            )
        mailfrom = config[section_name].get('mailfrom', None)
        if not mailfrom:
            mailfrom = config['mail'].get('mailfrom', None)
        if not mailfrom:
            raise ConfigException(
                "Please specify mailfrom either in '{0}' or in 'mail'".format(
                    section_name
                )
            )
        mailcfg = MailConfig(
            mailto,
            mailfrom,
            config['mail'].get('smtp', 'smtp')
        )
    else:
        mailcfg = None

    # if path does not end with /, trouble ahead with rsync.
    src_dir, dst_dir = (
        path if path.endswith('/') else path + '/'
        for path in (src_dir, dst_dir)
    )

    now = datetime.datetime.now()
    nowdir = os.path.join(
        '%i' % now.year,
        '%i' % now.month,
        '%i' % now.day,
        '%i_%i_%i.%i' % (now.hour, now.minute, now.second, now.microsecond)
    )

    os.makedirs(os.path.join(logbase, nowdir))
    log_fnames = (
        os.path.join(logbase, nowdir, fname)
        for fname in ('rsync_out', 'rsync_err', 'rsync_ret')
    )
    log_fds = (
        open(fname, 'w')
        for fname in log_fnames
    )

    ctx_args = (
        host,
        src_dir,
        dst_dir,
        os.path.join(
            logbase, nowdir, '{}.log'.format(
                os.path.basename(sys.argv[0])
            )
        ),
        mailcfg,
        ) + tuple(log_fds)
    print(ctx_args)
    return Context(*ctx_args)


def setup_log(context):
    """Setup the logs for this script
    """
    logging.basicConfig(filename=context.logfile, level=logging.DEBUG)
    logger = logging.getLogger('main')
    # log to stdout
    logger.addHandler(StreamHandler(sys.stdout))
    return logger


def log2mail(context):

    if os.path.exists(context.log_ret_fd.name):
        returncode = open(context.log_ret_fd.name).read().strip()
    else:
        returncode = "unknown"

    taskdesc = 'backup of {0.host}:{0.src_dir} on {0.dst_dir}'.format(context)

    if returncode == '0':
        subject = '[success] {}'.format(taskdesc)
    else:
        subject = '[failed] {}'.format(taskdesc)
    msg = MIMEMultiPart(
        Subject=subject,
        From=context.mail.mailfrom,
        To=context.mail.mailto,
    )

    msg.preamble = '{}\nreturncode of rsync was {}\n'.format(
        subject,
        returncode
    )

    for name, fname in (
            'stdout.txt', context.log_out_fd.name,
            'stderr.txt', context.log_err_fd.name,
            ):
        textfile = MIMEApplication(
            open(fname).read(),
            Content_Disposition='attachment; filename="{}"'.format(name)
        )
        msg.attach(
            textfile
        )

    session = smtplib.SMTP(context.mail.smtp)
    session.sendmail(
        context.mail.mailfrom,
        [context.mail.mailto],
        msg.as_string()
    )
    session.quit()


if __name__ == '__main__':
    context = context()

    logger = setup_log(context)

    try:
        backup(context, logger)
    except BaseException as err:
        logger.exception("An error or interruption occured")
    finally:
        if context.mail:
            log2mail(context)
