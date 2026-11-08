import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mergeSaved} from '../static/review-state.js';

test('save merges derived identity while preserving typing and bound form references',()=>{
 const target={profile:{name:'张三'},cover:{title:'旧标题',story:'旧内容'},table:{rows:[{type:'体重',after:'50'}]},preview_keys:{cover:'old'}};
 const before=structuredClone(target),cover=target.cover,table=target.table;
 target.cover.story='正在输入的新内容';
 target.table.rows.push({type:'腰围',after:'60'});
 const saved=structuredClone(before);saved.cover.title='张女士';saved.preview_keys.cover='new';
 mergeSaved(target,saved,before);
 assert.equal(target.cover,cover);assert.equal(target.table,table);
 assert.equal(target.cover.story,'正在输入的新内容');assert.equal(target.cover.title,'张女士');
 assert.equal(target.table.rows.length,2);assert.equal(target.preview_keys.cover,'new');
});

test('mask save preserves existing table/cover handlers and exposes new review fields',()=>{
 const target={cover:{title:'标题'},table:{rows:[]}},before=structuredClone(target),table=target.table;
 mergeSaved(target,{...before,mask_edits:{'vs:front':{a1:{deleted:true}}}},before);
 assert.equal(target.table,table);assert.ok(target.mask_edits['vs:front']);
 target.table.rows.push({type:'身高'});assert.equal(table.rows.length,1);
});
