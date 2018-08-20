FROM python:3.7.0-alpine3.8
LABEL maintainer="luk.zim91@gmail.com"

COPY . /opt

RUN pip install --no-cache-dir -r /opt/requirements.txt && \
    rm -rf /tmp/* /var/tmp/*

WORKDIR /opt/app
ENTRYPOINT [ "python", "app.py" ]
EXPOSE 5000
