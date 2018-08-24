from flask import Flask, Response
from flask_sqlalchemy import SQLAlchemy
from flask import request
from sqlalchemy.orm.attributes import flag_modified
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
import tarfile
import docker
import enum
import os
from utils import fatal_if, POST_ONLY, allowed_file, ensure_dir
from werkzeug.utils import secure_filename
import string

###############################################################
# Preflight checks
################################################################
DOCKER_SOCKET_PATH = '/var/run/docker.sock'

fatal_if(
    not os.path.exists(DOCKER_SOCKET_PATH),
    'No Docker socket found at {}'.format(DOCKER_SOCKET_PATH), 1)

# The registry key
URI_REGISTRY_KEY = 'URI_DOCKER_REGISTRY'
fatal_if(
    not URI_REGISTRY_KEY in os.environ,
    'Key {} not found nin environment'.format(URI_REGISTRY_KEY), 2)
URI_REGISTRY = os.environ[URI_REGISTRY_KEY]

###############################################################
# Constants
################################################################
FILENAME = 'file'

# Where the train archives are saved to
TAR_FILEPATH = '/tmp/jobs'


###############################################################
# Setup and and Docker client
################################################################
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://' # In memory database
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
docker_client = docker.DockerClient(base_url='unix:/{}'.format(DOCKER_SOCKET_PATH))

# Dockerfile path
DOCKERFILE = os.path.abspath(os.path.join(app.instance_path, 'Dockerfile'))


################################################################
# Job state enum
################################################################
class JobState(enum.Enum):
    """
    Represents the states a TrainBuilderArchive job traverses.
    """
    JOB_SUBMTTED = 0
    TAR_SAVED = 1
    DOCKERFILE_BEING_ADDED = 2
    DOCKERFILE_ADDED = 3
    TRAIN_BEING_CREATED = 4
    TRAIN_SUBMITTED = 5


################################################################
# Train Archive Job
################################################################
class TrainArchiveJob(db.Model):

    # Regular primary key
    id = db.Column(db.Integer, primary_key=True)

    # Path to the tar file
    job_directory = db.Column(db.String(80), unique=False, nullable=True)

    # TrainID, as obtained from the TrainOffie
    file_name = db.Column(db.String(80), unique=False, nullable=False)

    # State of this archive job
    state = db.Column(db.Enum(JobState))

    def to_filepath(self):
        return os.path.abspath(os.path.join(self.job_directory, str(self.id) + ".tar"))


db.create_all()


################################################################
# Database functions
def create_job(filename):
    """Creates a new job and returns it"""

    allowed_characters = string.ascii_lowercase + string.digits + '_-'
    # First, make the filename secure
    filename = secure_filename(filename)

    # Now everything has to be lowercase
    filename = filename.lower()

    # All non allowed characters are replaced by _
    problem_chars = [c for c in filename if c not in allowed_characters]
    for p in problem_chars:
        filename = filename.replace(p, '_')

    # If the filename now ends with _, just append s
    if filename.endswith('_'):
        filename = filename + 's'

    # Split the .tar ending from the file
    if filename.endswith('.tar'):
        filename = '.'.join(filename.split('.')[:-1])

    # Append train_ to the name, as the naming conventions for train requires
    if not filename.startswith("train_"):
        filename = "train_" + filename

    # Create a new trainArchiveJob
    job = TrainArchiveJob(
        job_directory=TAR_FILEPATH,
        file_name=filename,
        state=JobState.JOB_SUBMTTED
    )
    db.session.add(job)
    db.session.commit()
    return job


def update_job_state(job, state):
    """
    Updates the job state in the persistence
    """
    job.state = state
    flag_modified(job, 'state')
    db.session.merge(job)
    db.session.commit()


################################################################
# Responses
################################################################
def failure(msg):
    return Response('{"success": "false", "msg": "{}"}'.format(msg),
                    status=201, mimetype='application/json')


SUCCESS = Response('{"success": "true"}', status=200, mimetype='application/json')


################################################################
# Route for adding new train archives
################################################################
@app.route('/', methods=POST_ONLY)
def index():

    # check if the post request has the file part
    if FILENAME not in request.files:
        return failure("Field with name {} was not submitted".format(FILENAME))

    file = request.files[FILENAME]

    # if user does not select file, browser also
    # submit a empty part without filename
    if file:
        if file.filename == '':
            return failure("No file was selected")

        if allowed_file(file.filename, 'tar'):

            # Create a new job for this tar file
            job = create_job(file.filename)
            filepath = job.to_filepath()
            print("Saving to: {}".format(filepath))
            file.save(filepath)

            # Update the job now that the tarfile has been saved
            update_job_state(job, state=JobState.TAR_SAVED)
            return SUCCESS
    return failure("No file was selected or file is not a .tar file.")


##################################################################
# Define the background jobs that this Flask application performs
##################################################################
def process_jobs(jobs):

    for job_item in jobs:
        func = job_item[0]
        from_state = job_item[1]
        while_state = job_item[2]
        to_state = job_item[3]

        # First, select the first job with the property
        job = db.session.query(TrainArchiveJob).filter_by(state=from_state).first()
        if job:
            # Update the job state to the processing state
            update_job_state(job, while_state)
    
            # apply the processor function to the job
            func(job)
    
            # update the job state to the to_state
            update_job_state(job, to_state)


def background_job():
    """
    Adds the Dockerfile to the next tar file
    """
    def func1(job: TrainArchiveJob):

        # Add the Dockerfile to the archive. Note that we need to open specify the 'append: a' mode
        # for opening the file
        print("Add Dockerfile to Job: {}".format(job.id))
        with tarfile.open(job.to_filepath(), 'a') as tar:
            tar.add(DOCKERFILE, arcname='Dockerfile')
        print("Dockerfile has been added to job to Job: {}".format(job.id))
    
    def func2(job: TrainArchiveJob):
        # Open the Tarfile of this job and use it as the build context for the generated Docker archive
        repository = '{}/{}:immediate'.format(URI_REGISTRY, job.file_name)
        with open(job.to_filepath(), 'r') as f:
            print("Buildin Image")
            docker_client.images.build(
                fileobj=f,
                custom_context=True,
                tag=repository)
        docker_client.images.push(repository)
        print("Pushing to repository: {}".format(repository))
        print("Push successful")

    jobs = [ (func1, JobState.TAR_SAVED, JobState.DOCKERFILE_BEING_ADDED, JobState.DOCKERFILE_ADDED),
             (func2, JobState.DOCKERFILE_ADDED, JobState.TRAIN_BEING_CREATED, JobState.TRAIN_SUBMITTED) ]
    process_jobs(jobs)


##################################################################
# Configure the scheduler
##################################################################
scheduler = BackgroundScheduler()
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

scheduler.add_job(
    func=background_job,
    trigger=IntervalTrigger(seconds=1),
    id='add_dockerfile',
    name='Adds Dockerfile to the tar archive',
    replace_existing=True)


if __name__ == '__main__':

    ensure_dir(TAR_FILEPATH)
    app.run(host='0.0.0.0', port=9090)

