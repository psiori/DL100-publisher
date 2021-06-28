# DL100-publisher
This software makes use of the https://github.com/pjkundert/cpppo library to poll sensor readings from the SICK DL100 sensor and sends them over zmq connection (network or ipc).

To install all necessary requirements, run
```console
$ python -m venv .venv  # to create a virtual env
$ source .venv/bin/activate

(.venv) $ pip install -r requirements.txt
```

# Usage
## Library use

Add the directory containing `dl100_publisher.py` to your `sys.path` and
```
from dl100_publisher import Publisher
```
You can then intantiate a Publisher and connect to the socket inside your
library

## Standalone component

```console
$ python -m DL100_publisher [--dl100-ip=192.168.101.217] [--dl100-port=44818] [--connect-str='tcp://localhost5559'] [--cycle=1/30]
```
