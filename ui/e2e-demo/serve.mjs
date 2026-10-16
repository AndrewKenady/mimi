// A tiny stand-in for GitHub Pages, for the demo tests: the repo's site/ at /mimi/, the demo
// build at /mimi/demo/, folders answer with their index.html (and a slash redirect), byte
// ranges work, and anything missing gets site/404.html with a 404 status, as on Pages.
//
//   node e2e-demo/serve.mjs [port]
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ui = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const site = resolve(ui, '..', 'site');
const demo = resolve(ui, 'build-demo');
const port = Number(process.argv[2] || process.env.PORT || 7690);
const TYPES = {
	'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
	'.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json',
	'.pbf': 'application/x-protobuf', '.pmtiles': 'application/octet-stream', '.txt': 'text/plain'
};

function locate(pathname) {
	if (!pathname.startsWith('/mimi/')) return null;
	const rest = pathname.slice('/mimi/'.length);
	const [root, rel] = rest === 'demo' || rest.startsWith('demo/') ? [demo, rest.slice(5)] : [site, rest];
	const file = normalize(join(root, rel));
	return file.startsWith(root) ? file : null;
}

function send(res, file, status, req) {
	const size = statSync(file).size;
	const headers = { 'content-type': TYPES[extname(file)] || 'application/octet-stream', 'accept-ranges': 'bytes', 'cache-control': 'no-cache' };
	const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range || '');
	if (m && status === 200) {
		const start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
		const end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
		res.writeHead(206, { ...headers, 'content-range': `bytes ${start}-${end}/${size}`, 'content-length': end - start + 1 });
		return createReadStream(file, { start, end }).pipe(res);
	}
	res.writeHead(status, { ...headers, 'content-length': size });
	if (req.method === 'HEAD') return res.end();
	createReadStream(file).pipe(res);
}

createServer((req, res) => {
	const url = new URL(req.url, 'http://localhost');
	let pathname;
	try {
		pathname = decodeURIComponent(url.pathname);
	} catch {
		pathname = url.pathname;
	}
	const file = locate(pathname);
	if (file && existsSync(file) && statSync(file).isDirectory()) {
		if (!pathname.endsWith('/')) {
			res.writeHead(301, { location: url.pathname + '/' + url.search });
			return res.end();
		}
		if (existsSync(join(file, 'index.html'))) return send(res, join(file, 'index.html'), 200, req);
	} else if (file && existsSync(file)) return send(res, file, 200, req);
	send(res, join(site, '404.html'), 404, req);
}).listen(port, '127.0.0.1', () => console.log(`Pages stand-in: http://127.0.0.1:${port}/mimi/ (demo at /mimi/demo/)`));
