#!/bin/bash
ARGUMENTS="$*"

if [[ "$ARGUMENTS" == *"--no-cache"* ]]; then
  docker build --no-cache --pull -t "seo2:3.0.2" .
else
  docker build -t "seo2:3.0.2" .
fi
