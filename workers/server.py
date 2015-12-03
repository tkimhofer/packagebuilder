#!/usr/bin/env python

import time
import sys
import json
import os
import subprocess
import platform
import uuid
import stomp
import logging
# Modules created by Bioconductor
from bioconductor.config import BROKER

logging.basicConfig(format='%(levelname)s: %(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    level=logging.DEBUG)

ENVIR = {
    'packagebuilder_home': "/home/mtmorgan/a/packagebuilder/workers"
}

TOPICS = {
    "jobs": "/topic/buildjobs",
    "events": "/topic/builderevents"
}

BIOC_R_MAP = {"2.7": "2.12", "2.8": "2.13", "2.9": "2.14",
    "2.10": "2.15", "2.14": "3.1", "3.0": "3.1",
    "3.1": "3.2", "3.2": "3.2", "3.3": "3.3"} 

# FIXME Get this information dynamically.  Consider bioc-cm or
#       master.bioconductor.org/config.yaml

builder_id = platform.node().lower().replace(".fhcrc.org", "")
if sys.platform == "win32":
    # bad hardcoding! I don't know why this is necessary:
    if builder_id in ["windows1", "windows2"]:
        os.environ["USERDNSDOMAIN"] = "bioconductor.org"
    if "USERDNSDOMAIN" in os.environ:
        builder_id += "." + os.environ['USERDNSDOMAIN'].lower()
builder_id = builder_id.replace(".local", "")
## Temporary hack
if (builder_id.lower().startswith("dhcp") or \
  builder_id == 'PHS-ITs-Lion-Test-MacBook.local'):
    if ("PACKAGEBUILDER_HOST" in os.environ.keys()):
        builder_id = os.environ["PACKAGEBUILDER_HOST"]
    else:
        logging.error("main() Cannot determine who I am")
        raise
shell_ext = ".bat"
if (platform.system() == "Darwin" or platform.system() == "Linux"):
    shell_ext = ".sh"

# TODO: Name the callback for it's functionality, not usage.  This
# seems like it's as useful as 'myFunction' or 'myMethod'.  Why not
# describe capability provided ?
class MyListener(stomp.ConnectionListener):
    def on_connecting(self, host_and_port):
        logging.debug('on_connecting() %s %s.' % host_and_port)

    def on_connected(self, headers, body):
        logging.debug('on_connected() %s %s.' % (headers, body))

    def on_disconnected(self):
        logging.debug('on_disconnected().')

    def on_heartbeat_timeout(self):
        logging.debug('on_heartbeat_timeout().')

    def on_before_message(self, headers, body):
        logging.debug('on_before_message() %s %s.' % (headers, body))
        return headers, body

    def on_receipt(self, headers, body):
        logging.debug('on_receipt() %s %s.' % (headers, body))

    def on_send(self, frame):
        logging.debug('on_send() %s %s %s.' %
                      (frame.cmd, frame.headers, frame.body))

    def on_heartbeat(self):
        logging.debug('on_heartbeat().')

    def on_error(self, headers, message):
        logging.debug('on_error(): "%s".' % message)

    def on_message(self, headers, body):
        # FIXME : The maps defined above seem to be an anti-pattern.
        # Also, it's very odd IMHO that we're invoking 'global' here.
        # The variable is in scope and we're not attempting any read
        # or assignment.
        global shell_ext

        logging.info("Message received")
        try:
            received_obj = json.loads(body)
        except ValueError:
            logging.error("on_message() ValueError: invalid JSON?")
            return()
        if ('job_id' in received_obj.keys()): # ignore malformed messages
            job_id = received_obj['job_id']
            bioc_version = received_obj['bioc_version']

            job_dir = os.path.join(ENVIR['packagebuilder_home'], "jobs")
            if not os.path.exists(job_dir):
                os.mkdir(job_dir)
            job_dir = os.path.join(job_dir, job_id)
            if not os.path.exists(job_dir):
                os.mkdir(job_dir)
            r_libs_dir = os.path.join(job_dir, "R-libs")
            if not os.path.exists(r_libs_dir):
                os.mkdir(r_libs_dir)
            jobfilename = os.path.join(ENVIR['packagebuilder_home'], job_dir,
                                       "manifest.json")

            jobfile = open(jobfilename, "w")
            jobfile.write(body)
            jobfile.close
            logging.debug("on_message() job_dir = %s." % job_dir)

            shell_cmd = os.path.join(ENVIR['packagebuilder_home'],
                                     "%s%s" % (builder_id, shell_ext))
            logging.debug("on_message() shell_cmd = %s." % shell_cmd)

            builder_log = open(os.path.join(job_dir, "builder.log"), "w")
            subprocess.Popen([shell_cmd, jobfilename, bioc_version,],
                             stdout=builder_log, stderr=subprocess.STDOUT)
            ## TODO - somehow close builder_log filehandle if possible
            msg_obj = {}
            msg_obj['builder_id'] = builder_id
            msg_obj['body'] = "Got build request..."
            msg_obj['first_message'] = True
            msg_obj['job_id'] = job_id
            msg_obj['client_id'] = received_obj['client_id']
            msg_obj['bioc_version'] = bioc_version
            json_str = json.dumps(msg_obj)
            stomp.send(destination=TOPICS['events'], body=json_str,
                       headers={"persistent": "true"})
            logging.info("Reply sent")
        else:
            logging.error("on_message() Invalid JSON: missing job_id key.")

        # Acknowledge that the message has been processed
        self.message_received = True

try:
    stomp = stomp.Connection([(BROKER['host'], BROKER['port'])])
    stomp.set_listener('', MyListener())
    stomp.start()
    # optional connect keyword args "username" and "password" like so:
    # stomp.connect(username="user", password="pass")
    stomp.connect() # clientid=uuid.uuid4().hex)
    logging.info("Connected to '%s:%s'." % (BROKER['host'], BROKER['port']))
    stomp.subscribe(destination=TOPICS['jobs'], id=uuid.uuid4().hex,
                    ack='client')
    logging.info("Subscribed to destination %s" % TOPICS['jobs'])
except Exception as e:
    logging.error("main() Could not connect to ActiveMQ: %s." % e)
    raise

logging.info('Waiting for messages; CTRL-C to exit.')

while True:
    if logging.getLogger().isEnabledFor("debug"):
        logging.debug("main() Waiting to do work.")
    time.sleep(60 * 5)

logging.info("Done.")
