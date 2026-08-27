'use strict';

// Runs from `npm install`. A failure here must not fail the install: the bin
// shim retries the same bootstrap on first use, so a user who is only missing
// Python can install it afterwards and carry on.

const { ensureInstalled } = require('./bootstrap');

try {
  ensureInstalled({ log: (message) => process.stdout.write(`${message}\n`) });
  process.stdout.write('dexport: ready — run `dexport --help`.\n');
} catch (error) {
  process.stderr.write(
    `\ndexport: could not set up its Python environment yet.\n${error.message}\n` +
      'On Debian/Ubuntu the venv module ships separately: apt install python3-venv.\n' +
      'Nothing is broken — the next `dexport` command retries this step.\n\n'
  );
}
