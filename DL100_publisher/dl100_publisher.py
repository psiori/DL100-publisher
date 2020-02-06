import argparse
import datetime
import os
import struct
import sys
import threading
import time

from typing import Dict, List, Optional, Tuple

import numpy as np
import zmq

import cpppo
from cpppo.server.enip import client, poll
from cpppo.server.enip.get_attribute import attribute_operations, proxy_simple as device


def str2bool(v: List[bool, str]):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


class Publisher:
    """
    The Publisher class connects via cpppo to an Sick DL100 distance sensor and publishes it's distance + velocity measurements via zmq.
    """

    def __init__(
        self,
        host: str = "192.168.100.236",
        port: int = 44818,
        zmq_port: int = 5557,
        verbose: bool = True,
    ):
        """Init method

        Parameters:
        host (str): The IP of the DL100 distance scanner
        port (int): The port used by the dl100 distance scanner
        zmq_port (int): The port used by zmq to publish values
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
            ("@0x23/1/24", "DINT"): 2,  # velocity
            ("@0x23/1/10", "DINT"): 1,  # distance
        }

    def toggle_zmq_active(self):
        if self.zmq_active:
            self.zmq_active = False
        else:
            self.zmq_active = True
        return self.zmq_active

    def callback_measurements(self, par: Tuple[str, str], val: List[float]):
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
                msg = f"Sending: {ts}, {val_type}, {val[0]}"
                msg = msg + " " * (80 - len(msg))
                sys.stdout.write("\r" + msg)

    def start_data_polling(self, cycle: float = 1 / 50):
        """
        Setup cpppo polling thread, reading the measurements from an Ethernet Connection to the Distance Scanner.

        Parameters:
        cycle (float): The cycle length for measurement polling
        """
        self.poller = threading.Thread(
            target=poll.poll,
            kwargs={
                "proxy_class": device,
                "address": (self.host, self.port),
                "cycle": cycle,
                "timeout": 0.5,
                "process": lambda par, val: self.callback_measurements(
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
        "--cycle",
        type=float,
        required=False,
        default=1 / 30,
        help="The cycle length of measurements published via zmq",
    )

    parser.add_argument(
        "--verbose",
        type=str2bool,
        required=False,
        default=True,
        help="Activates verbose output",
    )

    args = parser.parse_args()
    print(args)

    pub = Publisher(
        host=args.dl100_ip,
        port=args.dl100_port,
        zmq_port=args.zmq_port,
        verbose=args.verbose,
    )

    pub.start_data_polling(cycle=args.cycle)

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
