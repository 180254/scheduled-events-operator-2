#!/bin/bash
ARGUMENTS="$*"

if [[ "$ARGUMENTS" == *"--no-cache"* ]]; then
  docker build --no-cache --pull -t "seo2:2.0.0" .
else
  docker build -t "seo2:2.0.0" .
fi
