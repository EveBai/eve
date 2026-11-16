#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p dist
cp index.html style.css quiz.js homepage-plush-concept.png dist/
