#!/bin/bash

NAME="db3cerp"
DJANGODIR=/opt/db3cerp/ #Django project directory
USER=root # the user to run as
GROUP=root # the group to run as
NUM_WORKERS=1 # how many worker processes should Gunicorn spawn
DJANGO_SETTINGS_MODULE=db3cerp.settings # which settings file should Django use
DJANGO_WSGI_MODULE=db3cerp.wsgi # WSGI module name

echo "Starting $NAME as `whoami`"
cd /opt/db3cerp/
source venv/bin/activate
# Activate the virtual environment
cd $DJANGODIR
export DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
export PYTHONPATH=$DJANGODIR:$PYTHONPATH

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

# Start your Django Unicorn
# Programs meant to be run under supervisor should not daemonize themselves (do not use --daemon)
exec gunicorn  ${DJANGO_WSGI_MODULE}:application \
--name $NAME \
--workers $NUM_WORKERS \
--bind 0.0.0.0:8000 \
--user=$USER --group=$GROUP \
--log-level=debug \
--log-file=-
