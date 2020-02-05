import argparse
import datetime
import os
import struct
import sys
import threading
import time

from typing import Dict, List, Tuple

import numpy as np
import zmq

import cpppo
from cpppo.server.enip import client, poll
from cpppo.server.enip.get_attribute import attribute_operations, proxy_simple as device


def values_to_bytes(values: Dict) -> bytes:
    """
    Extract relevant information and convert them to bytes.
    """
    ts = struct.pack(">d", values.get("ts"))
    distance = struct.pack(">i", values.get("distance", np.nan))
    velocity = struct.pack(">i", values.get("velocity", np.nan))

    return ts + distance + velocity


class Publisher:
    """
    The Publisher class connects via cpppo to an Sick DL100 distance sensor and publishes it's distance + velocity measurements via zmq.
    """

    def __init__(
        self, host: str = "192.168.100.236", port: int = 44818, zmq_port: int = 5557
    ):
        """Init method

        Parameters:
        host (str): The IP of the DL100 distance scanner
        port (int): The port used by the dl100 distance scanner
        zmq_port (int): The port used by zmq to publish values
        """

        super().__init__()
        self.stop = False
        self.host = host
        self.port = port
        self.zmq_port = zmq_port

        self.poller = None
        self.values = {}  # { <parameter>: (<timer>, <value>), ... }

        self.keymap = {
            ("@0x23/1/10", "DINT"): "distance",
            ("@0x23/1/24", "DINT"): "velocity",
        }

        self.start_data_polling(cycle=1 / 50)

    def update_values(self, par: Tuple[str, str], val: List[float]):
        self.values.update(
            {
                "ts": time.time(),  # use python ts, since we do not receive a ts from the dl100.
                self.keymap[par]: val[0],
            }
        )

    def start_data_polling(self, cycle: float = 1 / 50):
        """
        Setup cpppo polling thread, reading the measurements from an Ethernet Connection to the Distance Scanner.

        Parameters:
        cycle (float): The cycle length of polling measurments from the distance scanner
        """
        self.values = {}
        self.poller = threading.Thread(
            target=poll.poll,
            kwargs={
                "proxy_class": device,
                "address": (self.host, self.port),  # 44818: port for Ethernet IP
                "cycle": cycle,
                "timeout": 0.5,
                "process": lambda par, val: self.update_values(par=par, val=val),
                "params": list(self.keymap.keys()),
            },
        )
        self.poller.daemon = True
        self.poller.start()

    def setup_zmq(self):
        context = zmq.Context()
        self.pub_socket = context.socket(zmq.PUB)
        print("Publishing zmq msgs on port {port}".format(port=self.zmq_port))
        bind_addr = "tcp://*:{port}".format(port=self.zmq_port)
        self.pub_socket.bind(bind_addr)

    def destroy_zmq(self):
        self.pub_socket.close()
        print(f"\nClosing port {self.zmq_port}")

    def run(self, cycle: float = 1 / 30):
        """
        Opens a tcp socket and immediately starts sending measurement messages with specified cycletime.

        Parameters:
        cycle (float): The cycle length of measurements published via zmq
        """
        self.setup_zmq()
        try:
            a = 0
            while True:
                t0 = time.time()

                if self.values:
                    age = time.time() - self.values["ts"]

                    if age > cycle:
                        # only send recent values
                        continue

                    self.pub_socket.send(values_to_bytes(values=self.values.copy()))
                    msg = f"Sending: {self.values}"
                    msg = msg + " " * (80 - len(msg))
                    sys.stdout.write("\r" + msg)

                time.sleep(cycle - (time.time() - t0))
        except KeyboardInterrupt:
            self.destroy_zmq()
            pass


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
        default="192.168.100.236",
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
        "--zmq_cycle",
        type=float,
        required=False,
        default=1 / 30,
        help="The cycle length of measurements published via zmq",
    )

    args = parser.parse_args()
    print(args)

    pub = Publisher(host=args.dl100_ip, port=args.dl100_port, zmq_port=args.zmq_port)
    pub.run(cycle=args.zmq_cycle)


if __name__ == "__main__":
    main()
