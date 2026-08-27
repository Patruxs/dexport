#!/usr/bin/env node
'use strict';

// `dexport` on PATH: make sure the private virtualenv is there, then hand the
// whole argv over to the Python CLI and mirror its exit status.

const { spawnSync } = require('node:child_process');
const { ensureInstalled, venvPython, venvScript } = require('./bootstrap');

try {
  // Normally a no-op; it only does work when `npm install` ran with
  // --ignore-scripts, or the postinstall failed and the user fixed Python.
  ensureInstalled({ log: (message) => process.stderr.write(`${message}\n`), stdout: 2 });
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}

const args = process.argv.slice(2);
const script = venvScript();
const [command, argv] = script ? [script, args] : [venvPython(), ['-m', 'dexport', ...args]];

const result = spawnSync(command, argv, { stdio: 'inherit' });
if (result.error) {
  process.stderr.write(`${result.error.message}\n`);
  process.exit(1);
}
// Killed by a signal (Ctrl-C): report it the way a shell would.
process.exit(result.status === null ? 130 : result.status);
