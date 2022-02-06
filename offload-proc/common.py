#!/usr/bin/env python3

import os
import datetime
import subprocess
import random
import tempfile

import email
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
import mimetypes

# ---------------------------------------
#   Email Utilities
# ---------------------------------------
class EmailUtils:
    @staticmethod
    def _send_msg(msg):
        with tempfile.NamedTemporaryFile(suffix='.eml', delete=False) as eml_f:
            eml_f.write(msg.as_bytes())
            eml_f.flush()
            subprocess.check_call(f'sendmail -t < {eml_f.name}', shell=True)

    @staticmethod
    def _gen_msg_id():
        dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        return f'<{dt}.{"%016x" % random.randrange(16 ** 16)}@hauto-offload.local>'

    @staticmethod
    def send_email_text(email_addr, subject, body):
        msg = MIMEMultipart()
        msg['To'] = email_addr
        msg['From'] = f'Automation Bot <{email_addr}>'
        msg['In-Reply-To'] = msg['From']
        msg['Subject'] = subject
        msg['Message-Id'] = EmailUtils._gen_msg_id()
        body = MIMEText(f'<html><body>{body}</body></html>', _subtype='html')
        msg.attach(body)
        EmailUtils._send_msg(msg)

    @staticmethod
    def send_email_image(email_addr, subject, img_fname):
        msg = MIMEMultipart()
        msg['To'] = email_addr
        msg['From'] = f'Automation Bot <{email_addr}>'
        msg['In-Reply-To'] = msg['From']
        msg['Subject'] = subject
        msg['Message-Id'] = EmailUtils._gen_msg_id()
        message = '<html><body><img src="cid:img_payload"/></body></html>'
        body = MIMEText(message, _subtype='html')
        msg.attach(body)
        with open(img_fname, 'rb') as fd:
            mimetype, mimeencoding = mimetypes.guess_type(img_fname)
            if mimeencoding or (mimetype is None):
                mimetype = 'application/octet-stream'
            maintype, subtype = mimetype.split('/')
            if maintype == 'text':
                attachment = MIMEText(fd.read(), _subtype=subtype)
            else:
                attachment = MIMEBase(maintype, subtype)
                attachment.set_payload(fd.read())
                email.encoders.encode_base64(attachment)
            attachment.add_header('Content-ID', '<img_payload>')
            attachment.add_header('Content-Disposition', 'inline', filename=img_fname)
        msg.attach(attachment)
        EmailUtils._send_msg(msg)

    @staticmethod
    def send_email_html(email_addr, subject, body_html, inline_images = {}, attachments = []):
        msg = MIMEMultipart()
        msg['To'] = email_addr
        msg['From'] = f'Automation Bot <{email_addr}>'
        msg['In-Reply-To'] = msg['From']
        msg['Subject'] = subject
        msg['Message-Id'] = EmailUtils._gen_msg_id()
        body = MIMEText(f'<html>{body_html}</html>', _subtype='html')
        msg.attach(body)
        for cid, img_fname in inline_images.items():
            with open(img_fname, 'rb') as fd:
                mimetype, mimeencoding = mimetypes.guess_type(img_fname)
                if mimeencoding or (mimetype is None):
                    mimetype = 'application/octet-stream'
                maintype, subtype = mimetype.split('/')
                if maintype == 'text':
                    attachment = MIMEText(fd.read(), _subtype=subtype)
                else:
                    attachment = MIMEBase(maintype, subtype)
                    attachment.set_payload(fd.read())
                    email.encoders.encode_base64(attachment)
                attachment.add_header('Content-ID', f'<{cid}>')
                attachment.add_header('Content-Disposition', 'inline', filename=img_fname)
            msg.attach(attachment)
        for att_fname in attachments:
            with open(att_fname, 'rb') as fd:
                part = MIMEApplication(fd.read(), Name=os.path.basename(att_fname))
            part['Content-Disposition'] = 'attachment; filename="%s"' % os.path.basename(att_fname)
            msg.attach(part)
        EmailUtils._send_msg(msg)
