// Copyright 2026 Revenax Digital Services
// Author: Mohamed A. Abdallah
//
// Ops-app database (Neon) + photo bucket (S3) side of the scripts/ops procedures.
//   node scripts/ops/neon.js delete    SKU...      remove product row, its change requests, its photo
//   node scripts/ops/neon.js sold      SKU...      mark sold
//   node scripts/ops/neon.js warehouse WH SKU...   set warehouse (after an Odoo move)
//   node scripts/ops/neon.js reprint   SKU...      put back in the label print queue
//   node scripts/ops/neon.js show      SKU...      print the rows
// Needs `pg` and `@aws-sdk/client-s3` resolvable (npm i pg @aws-sdk/client-s3 in a
// scratch dir and set NODE_PATH to its node_modules). Reads the ops server .env.
const path = require('path');
process.loadEnvFile(process.env.OPS_ENV || path.join(process.env.HOME, 'Projects/marjaan/marjaan-operations-server/.env'));
const { Client } = require('pg');
const BUCKET = 'marjaan-products-photos';

(async () => {
  const [cmd, ...args] = process.argv.slice(2);
  const c = new Client({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  await c.connect();
  try {
    if (cmd === 'delete') {
      const { S3Client, DeleteObjectCommand } = require('@aws-sdk/client-s3');
      const s3 = new S3Client({ region: 'us-east-1' });
      for (const sku of args) {
        const row = (await c.query('SELECT photo_url FROM products WHERE sku = $1', [sku])).rows[0];
        const cr = (await c.query('DELETE FROM change_requests WHERE sku = $1', [sku])).rowCount;
        const pr = (await c.query('DELETE FROM products WHERE sku = $1', [sku])).rowCount;
        let key = '-';
        if (row && row.photo_url) {
          key = decodeURIComponent(new URL(row.photo_url).pathname.slice(1));
          await s3.send(new DeleteObjectCommand({ Bucket: BUCKET, Key: key }));
        }
        console.log(sku, 'requests', cr, 'product', pr, 'photo', key);
      }
    } else if (cmd === 'sold') {
      const r = await c.query('UPDATE products SET sold = true WHERE sku = ANY($1) RETURNING sku', [args]);
      console.log('sold', r.rows.map((x) => x.sku).join(', '));
    } else if (cmd === 'warehouse') {
      const [wh, ...skus] = args;
      const r = await c.query('UPDATE products SET warehouse = $1 WHERE sku = ANY($2) RETURNING sku', [wh, skus]);
      console.log('warehouse', wh, r.rows.map((x) => x.sku).join(', '));
    } else if (cmd === 'reprint') {
      const r = await c.query('UPDATE products SET printed = false WHERE sku = ANY($1) RETURNING sku', [args]);
      console.log('queued', r.rows.map((x) => x.sku).join(', '));
    } else if (cmd === 'show') {
      const r = await c.query('SELECT sku, warehouse, weight, sold, printed, stocked, odoo_id, registered_by, created_at FROM products WHERE sku = ANY($1)', [args]);
      console.table(r.rows);
    } else {
      console.error('usage: neon.js delete|sold|warehouse|reprint|show ...');
      process.exitCode = 2;
    }
  } finally {
    await c.end();
  }
})();
