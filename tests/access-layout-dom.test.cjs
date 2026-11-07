/* CSS cascade regression: the global text-input width must not size radios. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'));
const w=dom.window,d=w.document;
try{
  for(const path of ['static/assets/app.css','static/assets/desktop.css']){
    const style=d.createElement('style');style.textContent=fs.readFileSync(path,'utf8');d.head.append(style);
  }
  for(const radio of d.querySelectorAll('.access-mode input[type="radio"]')){
    const css=w.getComputedStyle(radio);
    assert.equal(css.width,'16px','radio must not inherit the global 100% input width');
    assert.equal(css.minHeight,'0px','radio must not inherit the text-input minimum height');
    assert.equal(css.flexShrink,'0');
    const text=w.getComputedStyle(radio.nextElementSibling);
    assert.equal(text.minWidth,'0px','long labels can shrink inside the card');
    assert.equal(text.overflowWrap,'anywhere');
    assert.equal(w.getComputedStyle(radio.closest('label')).margin,'0px','global label margins cannot inflate cards');
  }
  for(const selector of ['.access-modes','.access-columns']){
    const css=w.getComputedStyle(d.querySelector(selector));
    assert.equal(css.alignItems,'start','cards retain their own content height');
    assert.match(css.gridTemplateColumns,/minmax\(0,\s*1fr\)/,'long paths cannot widen grid tracks');
  }
  const dialog=w.getComputedStyle(d.querySelector('#accessDialog'));
  assert.equal(dialog.boxSizing,'border-box');assert.equal(dialog.overflow,'hidden');
  assert.equal(dialog.overflowWrap,'anywhere');
  const body=d.querySelector('.access-body');
  assert.equal(w.getComputedStyle(body).overflowY,'auto');
  assert.equal(w.getComputedStyle(body).overflowX,'hidden');
  assert.ok(!body.contains(d.querySelector('#accessClose')));
  const rules=[...d.styleSheets].flatMap(sheet=>[...sheet.cssRules]);
  assert.ok(rules.some(rule=>rule.conditionText==='(max-width:760px)' && [...rule.cssRules].some(child=>
    child.selectorText==='.access-modes,.access-columns' && child.style.getPropertyValue('grid-template-columns')==='minmax(0,1fr)')),
    'narrow viewport switches both card grids to one shrinkable column');
  console.log('PASS access layout DOM/CSS cascade: radios, wrapping, compact cards, responsive grid');
}finally{w.close();}
