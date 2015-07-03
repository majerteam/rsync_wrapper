#!/usr/bin/env python3
# coding: utf-8

"""
Run rsync backup and log all data.

Python >= 3.3

See README.rst
"""


__author__ = 'Feth Arezki'
__licence__ = 'MIT'
__version__ = "1.0.0"


import collections
import configparser
import datetime
import logging
import os
import signal
import smtplib
import subprocess
import sys

from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
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
        'timeout_secs',
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

    handled_signals = (
        signal.SIGINT,
        signal.SIGKILL,
        signal.SIGQUIT,
    )

    def sig_handler(signum, frame):
        logger = logging.getLogger('main.sig_handler-{0}'.format(signum))

        logger.info(
            "Got signal %s, propagating to process %s",
            signum, process.pid
        )
        try:
            os.kill(process.pid, signum)
        except BaseException:
            logger.exception("Error while killing process : %s", process.pid)
            # not propagating error:
            #
            # no further processing is done, only logging,
            # and we need that logging whenever possible

    orig_handlers = {}
    status = ''

    for sig_x in handled_signals:
        # install own signals
        orig_handlers[sig_x] = signal.getsignal(sig_x)
        signal.signal(signal.SIGINT, sig_handler)

    if context.timeout_secs is None:
        process.wait()
    else:
        # After this delay, we'll abort
        logger.info(
            "Setting up alarm clock: "
            "we'll stop in %s seconds max",
            context.timeout_secs
        )
        try:
            process.wait(context.timeout_secs)
        except subprocess.TimeoutExpired:
            status = 'time expired'
            logger.error(
                'time expired, interrupting process %s with ^C',
                process.pid
            )
            os.kill(process.pid, signal.SIGINT)
            process.wait()

    for sig_x in handled_signals:
        # restore original signals
        signal.signal(signal.SIGINT, orig_handlers[sig_x])

    returncode = process.returncode

    if returncode == 0:
        logfn = logger.info
        status = "success"
    else:
        logfn = logger.critical
        status = status or "failure"

    context.log_ret_fd.write('{0}\n'.format(process.returncode))
    logfn('{0[0]} exited with status {1}'.format(command, returncode))

    for descr in (context.log_out_fd, context.log_err_fd, context.log_ret_fd):
        descr.close()

    return status


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

    timeout_secs = config[section_name].get('timeout_secs', '')
    if timeout_secs:
        timeout_secs = int(timeout_secs)
    else:
        timeout_secs = None

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
        timeout_secs,
        os.path.join(
            logbase, nowdir, '{}.log'.format(
                os.path.basename(sys.argv[0])
            )
        ),
        mailcfg,
        ) + tuple(log_fds)
    return Context(*ctx_args)


def setup_log(context):
    """Setup the logs for this script
    """
    logging.basicConfig(filename=context.logfile, level=logging.DEBUG)
    logger = logging.getLogger('main')
    # log to stdout
    logger.addHandler(StreamHandler(sys.stdout))
    return logger


def log2mail(context, status):
    logging.getLogger('main.log2mail').debug(
        "sending mail to %s", context.mail.mailto
    )

    if os.path.exists(context.log_ret_fd.name):
        returncode = open(context.log_ret_fd.name).read().strip()
    else:
        returncode = "unknown"

    taskdesc = 'backup of {0.host}:{0.src_dir} on {0.dst_dir}'.format(context)

    subject = '[{}] {}'.format(status, taskdesc)

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = context.mail.mailfrom
    msg['To'] = context.mail.mailto

    msg.preamble = 'mail sent by run_backup'

    readable = MIMEText(
        '{}\nreturncode of rsync was {}\n'.format(
            subject,
            returncode
        ).encode('utf-8'),
        'plain',
        'utf-8'
    )
    msg.attach(readable)

    for name, fname in (
            ('stdout.txt', context.log_out_fd.name),
            ('stderr.txt', context.log_err_fd.name),
            ('python.txt', context.logfile),
            ):
        textfile = MIMEApplication(
            open(fname, 'rb').read(),
            'application/text',
        )
        textfile.add_header('Content-Disposition', 'attachment', filename=name)
        msg.attach(textfile)

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
        status = backup(context, logger)
    except BaseException as err:
        logger.exception("An error or interruption occured")
        status = "problem occured"
    finally:
        if context.mail:
            log2mail(context, status)
