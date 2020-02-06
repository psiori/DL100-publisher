# DL100-publisher
This software makes use of the https://github.com/pjkundert/cpppo library to poll sensor readings from the SICK DL100 sensor and sends them over network.

To install all necessary requirements you may perform:
```console
$ python -m venv .venv
$ source .venv/bin/activate

(.venv) $ pip install -r requirements.txt
```

Run the DL100_publisher:

```console
$ python -m DL100_publisher [--dl100_ip=192.168.100.236] [--dl100_port=44818] [--zmq_port=5559] [--cycle=1/30]
```

Parameters explained: 
- `dl100_port` - The port used by the DL100 distance scanner
- `dl100_ip` - The IP of the DL100 distance scanner
- `zmq_port` - The port used by zmq to publish values
- `cycle` - The cycle length of measurements read from the scanner and forwarded via zmq