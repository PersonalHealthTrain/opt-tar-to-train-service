import sys
import os


###############################################################
# Utility functions
################################################################
def fatal_if(test, message, status):
    if test:
        print("FATAL: {}".format(message), file=sys.stderr)
        sys.stderr.flush()
        sys.exit(status)


def allowed_file(filename, ext):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in [ext]


def ensure_dir(filepath):
    if not os.path.exists(filepath):
        os.mkdir(filepath)


POST_ONLY = ['POST']
