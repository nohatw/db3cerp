#!/usr/bin/env bash

cd /opt/db3cerp/
source  venv/bin/activate
git pull origin main
python3 manage.py collectstatic --noinput
python3 manage.py makemigrations
python3 manage.py migrate
supervisorctl restart db3cerp
