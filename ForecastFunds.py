#!/usr/bin/python

import os
import datetime
import requests
import csv
import time
import random
from argparse import ArgumentParser
from tabulate import tabulate

def display_data(data):
    headers = ["Date", "Price/Cost", "Note"]
    table = tabulate(data, headers, tablefmt="fancy_grid")
    print(table)

if __name__ == "__main__":
    # Sample data, you can replace this with your actual data
    data = [
        ["2023-04-11", 100.00, "Groceries"],
        ["2023-04-12", 50.00, "Dinner with friends"],
        ["2023-04-15", 200.00, "Electricity bill"],
        # Add more rows as needed
    ]

display_data(data)
