FROM personalhealthtrain/train-template-python:latest
COPY . /pht_train
RUN chmod +x /pht_train/entrypoint.py

ENTRYPOINT [ "/pht_train/entrypoint.py" ]
