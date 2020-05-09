// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import finalhandler from 'finalhandler';
import http from 'http';
import serveStatic from 'serve-static';

const port = 8000;
const serve = serveStatic('.');
const server = http.createServer((req, res) => {
  serve(req as any, res as any, finalhandler(req, res));
});
console.log(`server running on port ${port}`);
server.listen(port);
