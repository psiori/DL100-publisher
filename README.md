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
$ python -m DL100_publisher [--dl100_ip=192.168.100.236] [--dl100_port=44818] [--zmq_port=5559] [--cycle=1/30] [--mode=multi]
```

Parameters explained: 
- `dl100_port` - The port used by the DL100 distance scanner
- `dl100_ip` - The IP of the DL100 distance scanner
- `zmq_port` - The port used by zmq to publish values
- `cycle` - The cycle length of measurements read from the scanner and forwarded via zmq
- `mode` - Choose wether to send small zmq-messages per received value, or aggregate distance+velocity into one zmq-message. Options: [single, multi]
  - `single` - Message Format: `timestamp`, `value_type` (1: distance, 2: velocity), `value`
  - `multi` - Message Format:  `timestamp` (of distance measurement), `distance_vaue`, `velocity_value`