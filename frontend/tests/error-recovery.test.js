import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const root = new URL('../src/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, root), 'utf8');

test('role workspaces are protected by route-level render error boundaries', () => {
  const main = read('main.jsx');
  assert.match(main, /RouteErrorBoundary/);
  assert.match(main, /homePath="\/patient"/);
  assert.match(main, /homePath="\/doctor"/);
  assert.match(main, /homePath="\/admin"/);
});

test('route error boundary always offers recovery instead of a blank screen', () => {
  const boundary = read('components/RouteErrorBoundary.jsx');
  assert.match(boundary, /Try this screen again/);
  assert.match(boundary, /Return to workspace/);
  assert.match(boundary, /saved information has not been changed/);
  assert.match(boundary, /window\.location\.assign/);
});

test('global and route-level error boundaries both exist', () => {
  assert.ok(fs.existsSync(new URL('components/GlobalErrorBoundary.jsx', root)));
  assert.ok(fs.existsSync(new URL('components/RouteErrorBoundary.jsx', root)));
});
