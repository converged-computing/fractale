#!/bin/bash
sudo kill -9 $(lsof -t -i:8089)
