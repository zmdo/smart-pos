import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/mask-editor-model.js',import.meta.url),'utf8');
const {movedPosition,stickerRect,editorEdits}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const panel={asset_id:'a1',size:[400,600]},face={source_face:0,sticker_size:[100,120],default_rect:[100,60,200,180],manual_position:null,deleted:false};
test('drag clamps to photo boundary without resizing sticker',()=>{
 assert.deepEqual(movedPosition(panel,face,10,-10),[.75,0]);
 assert.deepEqual(stickerRect(panel,{...face,manual_position:[.5,.5]}),[200,300,100,120]);
});
test('independent edits preserve identity across tabs and six-photo layout',()=>{
 const groups=[{scope:'three_views:all',panels:[{...panel,faces:[{...face,deleted:true}]}]},
 {scope:'vs:front',panels:[{...panel,faces:[{...face,manual_position:[.2,.3]}]}]}];
 const edits=editorEdits(groups);
 assert.equal(edits.length,2);assert.equal(edits[0].deleted,true);assert.equal(edits[1].deleted,false);
 edits[1].position[0]=.9;assert.equal(groups[1].panels[0].faces[0].manual_position[0],.2);
});
test('restoring automatic position recovers default geometry',()=>{
 assert.deepEqual(stickerRect(panel,face),[100,60,100,120]);
 assert.deepEqual(movedPosition(panel,face,.005,-.005),[.255,.095]);
});
