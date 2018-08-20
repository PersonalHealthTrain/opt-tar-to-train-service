FROM python:3.7.0-alpine3.8
LABEL maintainer="luk.zim91@gmail.com"

COPY . /opt

RUN addgroup -S flask && \
    adduser -S -G flask -D -H flask && \
    pip install --no-cache-dir -r /opt/requirements.txt && \
    chown -R flask:flask /opt && \
    rm -rf /tmp/* /var/tmp/*

USER flask
WORKDIR /opt/app
ENTRYPOINT [ "python", "app.py" ]
EXPOSE 5000
