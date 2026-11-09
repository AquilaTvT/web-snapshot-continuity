'use strict';
const express = require('express');
const app = express();
const etag = process.argv[2];
if (!['weak', 'strong'].includes(etag)) throw new Error('Choose weak or strong');
app.set('etag', etag);
const states = [
  {a: 'Admission: eligible.\n', b: 'Fee: 100 dollars.\n'},
  {a: 'Admission: ineligible.\n', b: 'Fee: 10 dollars.\n'},
  {a: 'Admission: eligible.\n', b: 'Fee: 100 dollars.\n'},
];
let phase = 0;
app.get('/a', (req, res) => res.type('text/plain').send(states[phase].a));
app.get('/b', (req, res) => res.type('text/plain').send(states[phase].b));
// Control is local to a private, ephemeral experiment server.
app.post('/phase/:phase', (req, res) => {
  const next = Number(req.params.phase);
  if (next !== phase + 1 || next > 2) return res.status(400).end();
  phase = next;
  return res.status(204).end();
});
const server = app.listen(0, '127.0.0.1', () => {
  process.stdout.write(JSON.stringify({port: server.address().port,
    express: require('express/package.json').version,
    etag: require('etag/package.json').version, mode: etag}) + '\n');
});
process.on('SIGTERM', () => server.close(() => process.exit(0)));
