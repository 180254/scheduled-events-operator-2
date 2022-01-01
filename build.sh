#!/bin/bash
ARGUMENTS="$*"

if [[ "$ARGUMENTS" == *"--no-cache"* ]]; then
  docker build --no-cache --pull -t "seo2:2.1.0" .
else
  docker build -t "seo2:2.1.0" .
fi
