import argparse
import datetime
import os
import random
import struct
import sys
import threading
import time

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import zmq

import cpppo
from cpppo.server.enip import client, poll
from cpppo.server.enip.get_attribute import attribute_operations, proxy_simple as device


def str2bool(v: Union[bool, str]):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")

def make_msg(ts, v1, v2):
        msg = f"{datetime.datetime.utcfromtimestamp(ts).isoformat()} - {ts:1.06f}, {v1:8.0f}, {v2:12.2f}"
        msg = msg + " " * (80 - len(msg))
        return msg


class Publisher:
    """
    The Publisher class connects via cpppo to an Sick DL100 distance sensor and publishes it's distance + velocity measurements via zmq.
    """

    def __init__(
        self,
        zmq_port: int,
        host: str,
        port: int = 44818,
        verbose: bool = True,
    ):
        """Init method

        Parameters:
        zmq_port (int): The port used by zmq to publish values
        host (str): The IP of the DL100 distance scanner
        port (int): The port used by the dl100 distance scanner
        verbose (bool): Activate verbose mode
        """

        self.host = host
        self.port = port  # 44818: port for Ethernet IP
        self.zmq_port = zmq_port
        self.verbose = verbose

        self.zmq_active = False
        self.pub_socket = None

        self.poller: Optional[threading.Thread] = None

        self.setup_zmq()

        self.keymap: Dict[Tuple[str, str], int] = {
            ("@0x23/1/10", "DINT"): 1,  # distance
            ("@0x23/1/24", "DINT"): 2,  # velocity
        }
        
        self.values = {}

    def toggle_zmq_active(self):
        if self.zmq_active:
            self.zmq_active = False
        else:
            self.zmq_active = True
        return self.zmq_active

    def callback_zmq_single(self, par: Tuple[str, str], val: List[float]):
        """
        Forward dl100 messages directly via zmq.
        message format: timestamp, value_type (1: distance, 2: velocity), value
        """
        ts = time.time()
        val_type = self.keymap[par]

        if self.zmq_active:
            bytes = (
                struct.pack(">d", ts)
                + struct.pack(">i", val_type)
                + struct.pack(">i", val[0])
            )
            self.pub_socket.send(bytes)

            if self.verbose:
                msg = make_msg(ts=ts, v1=val_type, v2=val[0])
                sys.stdout.write("\r" + msg)

    def callback_zmq_multi(self, par: Tuple[str, str], val: List[float]):
        """
        Forward messages once both measurements (distance + velocity) have arrived.
        message format: timestamp (of distance measurement), distance_vaue, velocity_value
        """
        ts = time.time()

        if par == ("@0x23/1/10", "DINT"):
            name = 'distance'
        elif par == ("@0x23/1/24", "DINT"):
            name = 'velocity'
        else:
            raise ValueError(f"Unknown value received: {par}")
        
        self.values.update(
            {
                f"ts_{name}": ts,
                f"{name}": val[0]
            }
        )   

        if self.zmq_active:
            if list(self.values.keys()) == ['ts_distance', 'distance', 'ts_velocity', 'velocity']:
                # value collection complete, now send them out via zmq
                bytes = (
                    struct.pack(">d", self.values['ts_distance'])
                    + struct.pack(">i", self.values['distance'])
                    + struct.pack(">i", self.values['velocity'])
                )
                self.pub_socket.send(bytes)

                if self.verbose:
                    msg = make_msg(ts=self.values['ts_distance'], v1=self.values['distance'], v2=self.values['velocity'])
                    sys.stdout.write("\r" + msg)

                # reset Dict
                self.values = {}
    
    def send_random_data(self, cycle: float = 1 / 50):
        prev_dist = 0
        try:
            while True:
                ts = time.time()
                dist = 2500 + int((random.random() - 0.5) * 1000)
                vel = (dist - prev_dist) * cycle

                bytes = (
                    struct.pack(">d", ts)
                    + struct.pack(">i", dist)
                    + struct.pack(">i", int(vel))
                )
                self.pub_socket.send(bytes)

                if self.verbose:
                    msg = make_msg(ts=ts, v1=dist, v2=vel)
                    sys.stdout.write("\r" + msg)

                prev_dist = dist
                time.sleep(max(0, cycle - (time.time()-ts)))

        except KeyboardInterrupt:
            pass

    def start_data_polling(self, cycle: float = 1 / 50, mode: str = 'multi'):
        """
        Setup cpppo polling thread, reading the measurements from an Ethernet Connection to the Distance Scanner.

        Parameters:
        cycle (float): The cycle length for measurement polling
        mode (str): 
        """
        if mode == 'single':
            callback = self.callback_zmq_single
        elif mode == 'multi':
            callback = self.callback_zmq_multi

        else:
            raise ValueError(f"Unknown polling_callback mode: {mode}")

        self.poller = threading.Thread(
            target=poll.poll,
            kwargs={
                "proxy_class": device,
                "address": (self.host, self.port),
                "cycle": cycle,
                "timeout": 0.5,
                "process": lambda par, val: callback(
                    par=par, val=val
                ),
                "params": list(self.keymap.keys()),
            },
        )
        self.poller.daemon = True
        self.poller.start()

    def setup_zmq(self):
        if self.pub_socket and not self.pub_socket.closed:
            self.destroy_zmq()

        context = zmq.Context()
        self.pub_socket = context.socket(zmq.PUB)
        print("Publishing zmq msgs on port {port}".format(port=self.zmq_port))
        bind_addr = "tcp://*:{port}".format(port=self.zmq_port)
        self.pub_socket.bind(bind_addr)
        self.zmq_active = True

    def destroy_zmq(self):
        self.zmq_active = False
        self.pub_socket.close()
        print(f"Closing port {self.zmq_port}")


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dl100_port",
        type=int,
        required=False,
        default=44818,
        help="The port used by the DL100 distance scanner",
    )
    parser.add_argument(
        "--dl100_ip",
        type=str,
        required=False,
        default="192.168.101.217",
        help="The IP of the DL100 distance scanner",
    )
    parser.add_argument(
        "--zmq_port",
        type=int,
        required=False,
        default=5559,
        help="The port used by zmq to publish values",
    )

    parser.add_argument(
        "--cycle",
        type=float,
        required=False,
        default=1 / 30,
        help="The cycle length of measurements published via zmq",
    )

    parser.add_argument(
        "--mode",
        type=str,
        required=False,
        default='multi',
        help="Choose wether to send small zmq-messages per received value, or aggregate distance+velocity into one zmq-message. Options: [single, multi]",
    )

    parser.add_argument(
        "--verbose",
        type=str2bool,
        required=False,
        default=True,
        help="Activates verbose output",
    )

    parser.add_argument(
        "--send-bullshit",
        type=str2bool,
        required=False,
        default=False,
        help="Send random sample data",
    )

    args = parser.parse_args()
    print(args)

    pub = Publisher(
        host=args.dl100_ip,
        port=args.dl100_port,
        zmq_port=args.zmq_port,
        verbose=args.verbose,
    )
    if args.send_bullshit:
        pub.send_random_data(cycle=args.cycle)
    else:
        pub.start_data_polling(cycle=args.cycle, mode=args.mode)

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
