'use strict';

// Shared plumbing for the npm wrapper.
//
// dexport is a Python program; npm only carries it. The wrapper keeps a
// private virtualenv next to the installed package, pip-installs the shipped
// sources into it once, and then the bin shim runs `python -m dexport` out of
// that venv. Nothing is installed into the user's system Python, and removing
// the npm package removes the venv with it.

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
// Deliberately not `.venv`: a contributor running `npm install` inside a
// checkout must not have the wrapper reach into the development virtualenv.
const VENV = path.join(ROOT, '.dexport-venv');
const STAMP = path.join(VENV, '.npm-install-stamp');
const IS_WINDOWS = process.platform === 'win32';
const MIN_PYTHON = [3, 11];

function packageVersion() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version;
}

function venvBin(name) {
  return IS_WINDOWS
    ? path.join(VENV, 'Scripts', `${name}.exe`)
    : path.join(VENV, 'bin', name);
}

function venvPython() {
  return venvBin('python');
}

/**
 * The console script pip installed, when it is there. Preferred over
 * `python -m dexport` so `--help` shows `dexport ...` as the program name.
 */
function venvScript() {
  const script = venvBin('dexport');
  return fs.existsSync(script) ? script : null;
}

/** Interpreters to try, in order. `DEXPORT_PYTHON` wins when set. */
function interpreterCandidates() {
  if (process.env.DEXPORT_PYTHON) return [[process.env.DEXPORT_PYTHON, []]];
  return IS_WINDOWS
    ? [['py', ['-3']], ['python', []], ['python3', []]]
    : [['python3', []], ['python', []]];
}

const PRINT_VERSION = 'import sys; print("%d.%d" % sys.version_info[:2])';

/** `[command, args, "3.14"]` for the first interpreter new enough to use. */
function findPython() {
  const seen = [];
  for (const [command, args] of interpreterCandidates()) {
    const probe = spawnSync(command, [...args, '-c', PRINT_VERSION], { encoding: 'utf8' });
    if (probe.error || probe.status !== 0) continue;
    const version = probe.stdout.trim();
    const [major, minor] = version.split('.').map(Number);
    if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) {
      return [command, args, version];
    }
    seen.push(`${command} (${version})`);
  }
  const found = seen.length ? ` Found: ${seen.join(', ')}.` : '';
  throw new Error(
    `dexport needs Python ${MIN_PYTHON.join('.')} or newer on PATH.${found}\n` +
      'Install it from https://www.python.org/downloads/ (or your package manager), ' +
      'or point DEXPORT_PYTHON at the interpreter to use.'
  );
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`\`${command} ${args.join(' ')}\` failed with exit code ${result.status}.`);
  }
}

/** True when the venv already holds this exact version of the package. */
function isUpToDate() {
  try {
    return fs.readFileSync(STAMP, 'utf8').trim() === packageVersion() && fs.existsSync(venvPython());
  } catch {
    return false;
  }
}

/**
 * Make sure the private virtualenv exists and holds the shipped sources.
 * Cheap and idempotent once installed: a single stamp-file read.
 */
function ensureInstalled({ log = () => {}, stdout = 'inherit' } = {}) {
  if (isUpToDate()) return;
  // `stdout` lets the bin shim push pip's chatter to fd 2, so a bootstrap on
  // first use cannot end up inside a redirected `dexport export > file`.
  const stdio = ['inherit', stdout, 'inherit'];

  const [command, args, version] = findPython();
  log(`dexport: creating a private virtualenv with Python ${version}...`);
  fs.rmSync(VENV, { recursive: true, force: true });
  run(command, [...args, '-m', 'venv', VENV], { stdio });

  log('dexport: installing the Python package (this runs once)...');
  // `--no-input` keeps pip from blocking on a prompt inside `npm install`.
  run(venvPython(), ['-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', ROOT], {
    stdio,
  });

  fs.writeFileSync(STAMP, `${packageVersion()}\n`);
}

module.exports = { ROOT, VENV, ensureInstalled, venvPython, venvScript, packageVersion };
