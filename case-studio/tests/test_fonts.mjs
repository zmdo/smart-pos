import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/fonts.js',import.meta.url),'utf8');
const {removeIndexedFonts,loadFonts,fontOptions}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('removing a table row preserves the remaining cells font assignments',()=>{
 const current={'table.rows.0.type':'a','table.rows.1.before':'b','table.rows.2.unit':'c','cover.title':'d'};
 assert.deepEqual(removeIndexedFonts(current,'table.rows',1),{'table.rows.0.type':'a','table.rows.1.unit':'c','cover.title':'d'});
 assert.equal(current['table.rows.2.unit'],'c');
});
test('deactivated font remains visible only for an existing selection',async()=>{
 await loadFonts(async()=>[{id:'a',name:'黑体',active:true},{id:'b',name:'<font>',active:false}],true);
 assert.ok(!fontOptions('').includes('value="b"'));
 assert.ok(fontOptions('b').includes('selected disabled'));
 assert.ok(fontOptions('b').includes('&lt;font&gt;'));
});
