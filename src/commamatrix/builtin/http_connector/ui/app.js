// builtin/http_connector/ui/app.js
/** @typedef {{origin_type?: string, platform?: string, http_user_id?: number}} DialogOrigin */
/** @typedef {{item_id: number|null, previous_item_id: number|null, item_type?: string, role?: string, content?: string, user?: string, origin?: DialogOrigin, created_at?: string|null, external_id?: string|null}} DialogItem */
/** @typedef {{tool_name?: string, tool_call_id?: string}} StreamMeta */
/** @typedef {{type?: string, item_id?: number|null, item_type?: string, role?: string, content?: string, error?: string, active?: boolean, previous_item_id?: number|null, stream_id?: string|null, meta?: StreamMeta}} StreamEvent */
/* global hljs, marked, DOMPurify */
(function(){
"use strict";

const DEBUG=true;
function debug(message,data){if(DEBUG)console.log("[CommaMatrix UI] "+message,data??"")}
window.__commamatrixUiLoaded=true;
window.addEventListener("error",event=>{console.error("[CommaMatrix UI] uncaught error",event.error||event.message);const error=document.getElementById("auth-error");if(error)error.textContent="Interface error: "+event.message});
window.addEventListener("unhandledrejection",event=>{console.error("[CommaMatrix UI] unhandled rejection",event.reason);const error=document.getElementById("auth-error");if(error)error.textContent="Interface error: "+(event.reason?.message||event.reason||"Unknown error")});
debug("script loaded",{path:location.pathname,hasToken:Boolean(localStorage.getItem("commamatrix_auth_token"))});

const messagesEl=document.getElementById("messages");
const inputEl=document.getElementById("input");
const sendBtn=document.getElementById("send-btn");
const statusEl=document.getElementById("status");
const userLabel=document.getElementById("user-label");
const passwordBtn=document.getElementById("password-btn");
const inviteBtn=document.getElementById("invite-btn");
const logoutBtn=document.getElementById("logout-btn");
const branchList=document.getElementById("branch-list");
const newBranchBtn=document.getElementById("new-branch-btn");
const activeBranchesBtn=document.getElementById("active-branches-btn");
const deletedBranchesBtn=document.getElementById("deleted-branches-btn");
const branchOpenBtn=document.getElementById("branch-open");
const branchCloseBtn=document.getElementById("branch-close");
const branchBackdrop=document.getElementById("branch-backdrop");
const authOverlay=document.getElementById("auth-overlay");
const authTitle=document.getElementById("auth-title");
const authDescription=document.getElementById("auth-description");
const authForm=document.getElementById("auth-form");
const authUsername=document.getElementById("auth-username");
const authPassword=document.getElementById("auth-password");
const authConfirmLabel=document.getElementById("auth-confirm-label");
const authConfirm=document.getElementById("auth-confirm");
const authSubmit=document.getElementById("auth-submit");
const authError=document.getElementById("auth-error");
const passwordOverlay=document.getElementById("password-overlay");
const passwordForm=document.getElementById("password-form");
const passwordError=document.getElementById("password-error");
const inviteOverlay=document.getElementById("invite-overlay");
const inviteUrl=document.getElementById("invite-url");

let inviteToken=new URLSearchParams(location.search).get("token");
let authToken=localStorage.getItem("commamatrix_auth_token");
let currentUser=null;
let authMode=inviteToken?"register":"login";
let activeStreamId=null;
let eventsTask=null;
let eventsAbortController=null;
let currentReader=null;
let typingIndicator=null;
let codeactSpinnerEl=null;
let codeactActiveEl=null;
let codeactStreamArgs="";
let codeactStreamToolId=null;
let lastWasCodeAct=false;
let activeStreams={};
let streamingPreviews={};
/** @type {Map<number, DialogItem>} */
let itemsById=new Map();
/** @type {Map<number, number[]>} */
let childrenByParent=new Map();
let selectedHeadId=null;
let newRootSelected=false;
/** @type {Map<number, number>} */
let selectedLeafByNode=new Map();
let expandedNodes=new Set();
let deletedRootIds=new Set();
let showDeletedBranches=false;
let pendingBranch=null;
let pendingMessage=null;
let pendingRoot=false;
let pendingRootContent="";
let historyLoaded=false;

function setAuthLocked(locked){
  document.body.classList.toggle("auth-locked",locked);
  if(locked){authOverlay.classList.remove("hidden");authOverlay.style.display="flex"}
  else{authOverlay.classList.add("hidden");authOverlay.style.display="none"}
}

function setAuthMode(mode){
  authMode=mode;
  const register=mode==="register";
  authTitle.textContent=register?"Create account":"Sign in";
  authDescription.textContent=register?"Use the one-time invitation to create an account.":"Use your CommaMatrix account to connect to this agent.";
  authConfirmLabel.hidden=!register;
  authConfirm.hidden=!register;
  authConfirm.required=register;
  authPassword.autocomplete=register?"new-password":"current-password";
  authSubmit.textContent=register?"Register":"Sign in";
  authError.textContent="";
  debug("auth mode changed",{mode});
}

function authHeaders(){return authToken?{Authorization:"Bearer "+authToken}:{};}

function browserTimezone(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone||"UTC"}catch{return "UTC"}}

async function authFetch(url,options={}){
  const headers={...authHeaders(),...(options.headers||{})};
  return fetch(url,{...options,headers});
}

function showAuth(message=""){
  debug("show auth",{mode:inviteToken?"register":"login",message});
  setAuthMode(inviteToken?"register":"login");
  authError.textContent=message;
  setAuthLocked(true);
  authUsername.focus();
}

function clearAuth(){
  if(eventsAbortController)eventsAbortController.abort();
  eventsTask=null;authToken=null;currentUser=null;historyLoaded=false;activeStreamId=null;
  sendBtn.textContent="Send";sendBtn.classList.remove("cancel");sendBtn.disabled=false;
  localStorage.removeItem("commamatrix_auth_token");
  hideTyping();messagesEl.replaceChildren();itemsById=new Map();childrenByParent=new Map();selectedHeadId=null;newRootSelected=false;selectedLeafByNode=new Map();expandedNodes=new Set();deletedRootIds=new Set();showDeletedBranches=false;activeStreams={};streamingPreviews={};pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";
  passwordBtn.hidden=true;inviteBtn.hidden=true;logoutBtn.hidden=true;userLabel.textContent="";statusEl.textContent="Sign in required";
  renderBranchPanel();
}

function applyUser(user){
  currentUser=user;loadDeletedBranches();showDeletedBranches=false;userLabel.textContent=user.username;passwordBtn.hidden=false;inviteBtn.hidden=!user.is_admin;logoutBtn.hidden=false;statusEl.textContent="Ready";setAuthLocked(false);
}

function deletedBranchesStorageKey(){
  const userId=currentUser?.id??currentUser?.username;
  return userId===undefined||userId===null?null:"commamatrix_deleted_branches:"+String(userId);
}

function loadDeletedBranches(){
  deletedRootIds=new Set();
  const key=deletedBranchesStorageKey();if(!key)return;
  try{
    const values=JSON.parse(localStorage.getItem(key)||"[]");
    if(Array.isArray(values))for(const value of values){const id=Number(value);if(Number.isFinite(id))deletedRootIds.add(id)}
  }catch{}
}

function saveDeletedBranches(){
  const key=deletedBranchesStorageKey();if(!key)return;
  try{localStorage.setItem(key,JSON.stringify([...deletedRootIds]))}catch{}
}

function isRootDeleted(rootId){return deletedRootIds.has(Number(rootId));}

/** @param {DialogItem} item */
function itemTime(item){
  const time=Date.parse(item&&item.created_at||"");
  return Number.isNaN(time)?0:time;
}

/**
 * @param {DialogItem} a
 * @param {DialogItem} b
 */
function compareItems(a,b){
  return itemTime(a)-itemTime(b)||Number(a.item_id)-Number(b.item_id);
}

/** @param {DialogItem|undefined} item */
function isUserItem(item){return Boolean(item&&item.role==="user");}

/** @param {DialogItem|undefined} item */
function isOpaqueItem(item){return Boolean(item&&typeof item.role!=="string")}

/** @param {DialogItem|undefined} item */
function isVisibleItem(item){return Boolean(item&&!isOpaqueItem(item))}

/** @param {DialogItem[]} items */
function rebuildGraph(items){
  itemsById=new Map();childrenByParent=new Map();
  for(const item of items){
    if(item.item_id===null||item.item_id===undefined)continue;
    itemsById.set(item.item_id,item);
  }
  for(const item of itemsById.values()){
    if(item.previous_item_id===null||item.previous_item_id===undefined)continue;
    const children=childrenByParent.get(item.previous_item_id)||[];
    children.push(item.item_id);childrenByParent.set(item.previous_item_id,children);
  }
  for(const [parent,children] of childrenByParent){
    children.sort((a,b)=>compareItems(itemsById.get(a),itemsById.get(b)));
    childrenByParent.set(parent,children);
  }
}

/** @returns {DialogItem[]} */
function childItems(itemId){
  return (childrenByParent.get(itemId)||[]).map(id=>itemsById.get(id)).filter(Boolean);
}

function chainContains(headId,itemId){
  const seen=new Set();let current=headId;
  while(current!==null&&current!==undefined&&!seen.has(current)){
    if(current===itemId)return true;
    seen.add(current);const item=itemsById.get(current);current=item?item.previous_item_id:null;
  }
  return false;
}

function currentChain(){
  const result=[];const seen=new Set();let current=selectedHeadId;
  while(current!==null&&current!==undefined&&!seen.has(current)){
    const item=itemsById.get(current);if(!item)break;
    result.push(item);seen.add(current);current=item.previous_item_id;
  }
  return result.reverse();
}

function rootIdForItem(itemId){
  const seen=new Set();let current=itemsById.get(itemId);let rootId=null;
  while(current&&!seen.has(current.item_id)){
    seen.add(current.item_id);if(isVisibleItem(current))rootId=current.item_id;
    if(current.previous_item_id===null||current.previous_item_id===undefined)break;
    current=itemsById.get(current.previous_item_id);
  }
  return rootId;
}

function nearestVisibleParentId(itemId){
  const seen=new Set();let current=itemsById.get(itemId)?.previous_item_id;
  while(current!==null&&current!==undefined&&!seen.has(current)){
    seen.add(current);const item=itemsById.get(current);if(!item)return null;
    if(isVisibleItem(item))return item.item_id;
    current=item.previous_item_id;
  }
  return null;
}

function latestVisibleItemId(startId){
  const start=itemsById.get(startId);if(!start)return null;
  let latest=null;const stack=[start];const seen=new Set();
  while(stack.length){
    const item=stack.pop();if(seen.has(item.item_id))continue;seen.add(item.item_id);
    if(isVisibleItem(item)&&(!latest||compareItems(latest,item)<0))latest=item;
    stack.push(...childItems(item.item_id));
  }
  return latest?latest.item_id:null;
}

function latestGlobalVisibleId(){
  const items=[...itemsById.values()].filter(item=>{
    if(!isVisibleItem(item))return false;
    const rootId=rootIdForItem(item.item_id);
    return rootId===null||!isRootDeleted(rootId);
  });
  if(!items.length)return null;
  items.sort(compareItems);return items[items.length-1].item_id;
}

function logicalChildren(itemId){
  const result=[];const seen=new Set();const queue=[...childItems(itemId)];
  while(queue.length){
    const item=queue.shift();if(seen.has(item.item_id))continue;seen.add(item.item_id);
    if(isUserItem(item)){result.push(item);continue}
    queue.push(...childItems(item.item_id));
  }
  result.sort(compareItems);return result;
}

/** @param {DialogItem} item @returns {DialogItem[]} */
function branchSiblings(item){
  const parentId=nearestVisibleParentId(item.item_id);
  if(parentId===null)return [];
  return logicalChildren(parentId).filter(isUserItem).sort(compareItems);
}

function visibleRoots(){
  return [...itemsById.values()].filter(item=>isVisibleItem(item)&&nearestVisibleParentId(item.item_id)===null);
}

function rememberCurrentSelection(){
  if(selectedHeadId===null||selectedHeadId===undefined)return;
  for(const item of currentChain())if(isUserItem(item))selectedLeafByNode.set(item.item_id,selectedHeadId);
}

function selectedVisibleId(){
  const visible=currentChain().filter(isVisibleItem);return visible.length?visible[visible.length-1].item_id:null;
}

function expandUserAncestors(itemId){
  let current=itemsById.get(itemId)?.previous_item_id;
  while(current!==null&&current!==undefined){
    const item=itemsById.get(current);if(!item)break;
    if(isUserItem(item))expandedNodes.add(item.item_id);
    current=item.previous_item_id;
  }
}

function selectBranchNode(itemId){
  const item=itemsById.get(itemId);if(!item)return;
  const preferred=selectedLeafByNode.get(itemId);
  selectedHeadId=preferred!==undefined&&chainContains(preferred,itemId)?preferred:(latestVisibleItemId(itemId)||itemId);
  newRootSelected=false;
  debug("branch selected",{itemId,selectedHeadId,preferred,visible:currentChain().filter(isVisibleItem).map(item=>item.item_id)});
  pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";expandUserAncestors(itemId);rememberCurrentSelection();renderHistory();closeBranchPanel();
}

function groupForDate(timestamp){
  const date=new Date(timestamp);if(Number.isNaN(date.valueOf()))return "older";
  const now=new Date();
  const dayStart=value=>{const result=new Date(value);result.setHours(0,0,0,0);return result};
  const dateStart=dayStart(date);const today=dayStart(now);const days=Math.floor((today-dateStart)/86400000);
  if(days===0)return "today";
  if(days===1)return "yesterday";
  const weekStart=new Date(today);const day=(weekStart.getDay()+6)%7;weekStart.setDate(weekStart.getDate()-day);
  if(dateStart>=weekStart)return "this week";
  if(date.getFullYear()===now.getFullYear()&&date.getMonth()===now.getMonth())return "this month";
  return "older";
}

/** @param {DialogItem} root @returns {DialogItem} */
function rootLatestLeaf(root){return itemsById.get(latestVisibleItemId(root.item_id))||root}

/** @param {DialogItem} root */
function branchPreview(root){
  const descendants=[];const queue=[...childItems(root.item_id)];const seen=new Set();
  while(queue.length){
    const item=queue.shift();if(seen.has(item.item_id))continue;seen.add(item.item_id);descendants.push(item);queue.push(...childItems(item.item_id));
  }
  descendants.sort(compareItems);
  const preview=descendants.find(item=>{
    const userInput=item.role==="user"&&["input","image_input","file_input"].includes(item.item_type);
    const assistantOutput=item.role==="assistant"&&["output","image_output","file_output"].includes(item.item_type);
    return userInput||assistantOutput;
  })||root;
  return preview.content||"[empty message]";
}

function updateBranchTabs(){
  activeBranchesBtn.classList.toggle("active",!showDeletedBranches);activeBranchesBtn.setAttribute("aria-selected",String(!showDeletedBranches));
  deletedBranchesBtn.classList.toggle("active",showDeletedBranches);deletedBranchesBtn.setAttribute("aria-selected",String(showDeletedBranches));
}

function selectReplacementRoot(excludedRootId){
  const roots=visibleRoots().filter(root=>root.item_id!==excludedRootId&&!isRootDeleted(root.item_id));
  roots.sort((a,b)=>itemTime(rootLatestLeaf(b))-itemTime(rootLatestLeaf(a))||Number(b.item_id)-Number(a.item_id));
  return roots[0]||null;
}

function setRootDeleted(rootId,deleted){
  if(deleted===isRootDeleted(rootId))return;
  if(deleted)deletedRootIds.add(Number(rootId));else deletedRootIds.delete(Number(rootId));saveDeletedBranches();
  const selectedRootId=selectedHeadId===null?null:rootIdForItem(selectedHeadId);
  if(deleted&&!showDeletedBranches&&selectedRootId===Number(rootId)){
    const replacement=selectReplacementRoot(Number(rootId));
    if(replacement){selectBranchNode(replacement.item_id);return}
    selectedHeadId=null;newRootSelected=true;
  }
  renderHistory();
}

function setBranchView(showDeleted){
  showDeletedBranches=showDeleted;
  const selectedRootId=selectedHeadId===null?null:rootIdForItem(selectedHeadId);
  if(!showDeleted&&selectedRootId!==null&&isRootDeleted(selectedRootId)){
    const replacement=selectReplacementRoot(selectedRootId);
    if(replacement){selectBranchNode(replacement.item_id);return}
    selectedHeadId=null;newRootSelected=true;renderHistory();return;
  }
  renderBranchPanel();
}

function renderBranchPanel(){
  updateBranchTabs();branchList.replaceChildren();
  const roots=visibleRoots().filter(root=>isRootDeleted(root.item_id)===showDeletedBranches).sort((a,b)=>itemTime(rootLatestLeaf(b))-itemTime(rootLatestLeaf(a))||Number(b.item_id)-Number(a.item_id));
  if(!roots.length){const empty=document.createElement("div");empty.className="branch-empty";empty.textContent=showDeletedBranches?"No deleted conversations.":"No conversations yet.";branchList.appendChild(empty);return}
  const groups=new Map();
  for(const root of roots){const group=groupForDate(itemTime(rootLatestLeaf(root)));const values=groups.get(group)||[];values.push(root);groups.set(group,values)}
  for(const group of ["today","yesterday","this week","this month","older"]){
    const values=groups.get(group);if(!values)continue;
    const section=document.createElement("section");section.className="branch-group";
    const title=document.createElement("div");title.className="branch-group-title";title.textContent="-- "+group+" --";section.appendChild(title);
    for(const root of values)section.appendChild(renderBranchNode(root,0));
    branchList.appendChild(section);
  }
}

/**
 * @param {DialogItem} item
 * @param {number} depth
 */
function renderBranchNode(item,depth){
  const node=document.createElement("div");node.className="branch-node";
  const row=document.createElement("div");row.className="branch-row";
  const onPath=selectedHeadId!==null&&chainContains(selectedHeadId,item.item_id);
  if(onPath)row.classList.add("active");
  if(item.item_id===selectedVisibleId())row.classList.add("current");
  const main=document.createElement("button");main.type="button";main.className="branch-row-main";main.style.paddingLeft=(6+depth*14)+"px";main.title="Select branch";
  const preview=document.createElement("span");preview.className="branch-preview";preview.textContent=depth===0?branchPreview(item):(item.content||"[empty message]");main.appendChild(preview);
  main.addEventListener("click",()=>selectBranchNode(item.item_id));row.appendChild(main);
  const children=logicalChildren(item.item_id);
  if(children.length){
    const toggle=document.createElement("button");toggle.type="button";toggle.className="branch-toggle";toggle.textContent=expandedNodes.has(item.item_id)?"⌄":"›";toggle.setAttribute("aria-expanded",String(expandedNodes.has(item.item_id)));toggle.setAttribute("aria-label",expandedNodes.has(item.item_id)?"Collapse branch":"Expand branch");toggle.title=toggle.getAttribute("aria-label");
    toggle.addEventListener("click",event=>{event.stopPropagation();if(expandedNodes.has(item.item_id))expandedNodes.delete(item.item_id);else expandedNodes.add(item.item_id);renderBranchPanel()});row.appendChild(toggle);
  }
  if(depth===0){
    const deleted=document.createElement("button");deleted.type="button";deleted.className="branch-delete";const isDeleted=isRootDeleted(item.item_id);deleted.textContent=isDeleted?"↩":"×";deleted.title=isDeleted?"Restore branch":"Hide branch";deleted.setAttribute("aria-label",deleted.title);deleted.addEventListener("click",event=>{event.stopPropagation();setRootDeleted(item.item_id,!isDeleted)});row.appendChild(deleted);
  }
  node.appendChild(row);
  if(expandedNodes.has(item.item_id)&&children.length){
    const nested=document.createElement("div");nested.className="branch-children";
    for(const child of children)nested.appendChild(renderBranchNode(child,depth+1));
    node.appendChild(nested);
  }
  return node;
}

function renderHistory(){
  hideTyping();messagesEl.replaceChildren();activeStreams={};streamingPreviews={};codeactActiveEl=null;codeactStreamArgs="";codeactStreamToolId=null;lastWasCodeAct=false;
  for(const item of currentChain())if(isVisibleItem(item))renderItem(item);
  rememberCurrentSelection();renderBranchPanel();syncActionState();scrollToBottom();
}

/** @param {DialogItem} item */
async function applyDialogItem(item){
  if(item.item_id===null||item.item_id===undefined||itemsById.has(item.item_id))return;
  debug("dialog item",{itemId:item.item_id,previousItemId:item.previous_item_id,role:item.role,itemType:item.item_type,origin:item.origin,selectedHeadId,newRootSelected,pendingParentId:pendingMessage?.parentId});
  const parentMissing=item.previous_item_id!==null&&item.previous_item_id!==undefined&&!itemsById.has(item.previous_item_id);
  itemsById.set(item.item_id,item);
  if(item.previous_item_id!==null&&item.previous_item_id!==undefined){const children=childrenByParent.get(item.previous_item_id)||[];children.push(item.item_id);children.sort((a,b)=>compareItems(itemsById.get(a),itemsById.get(b)));childrenByParent.set(item.previous_item_id,children)}
  if(parentMissing){
    await loadHistory(item.item_id);
    return;
  }
  let shouldSelect=selectedHeadId===null||item.previous_item_id===selectedHeadId;
  if(pendingMessage&&isUserItem(item)&&item.previous_item_id===pendingMessage.parentId&&item.content===pendingMessage.content){shouldSelect=true;newRootSelected=false;pendingMessage=null;pendingBranch=null;pendingRoot=false;pendingRootContent=""}
  if(shouldSelect){selectedHeadId=item.item_id;rememberCurrentSelection();renderHistory()}
  else renderBranchPanel();
}

/** @param {DialogItem} item */
function createMessageMeta(item){
  const meta=document.createElement("div");meta.className="message-meta";
  const date=item.created_at?new Date(item.created_at):null;const stamp=date&&!Number.isNaN(date.valueOf())?date.toLocaleString("en-GB",{hour12:false,hour:"2-digit",minute:"2-digit",day:"2-digit",month:"2-digit",year:"2-digit"}).replace(", "," "):"";
  meta.textContent=stamp?"["+stamp+"]":"";return meta;
}

/** @param {DialogItem} item */
function displayUserName(item){
  const user=typeof item.user==="string"?item.user.trim():"";
  if(user){
    const separator=user.indexOf(":");
    if(separator>=0){
      const platform=user.slice(0,separator);
      if(platform==="http") return currentUser?.username||"User";
      return user.slice(separator+1)||user;
    }
    return user;
  }
  return currentUser?.username||"User";
}

/** @param {DialogItem} item */
function createUserEntry(item){
  const wrapper=document.createElement("div");wrapper.className="message-entry user-entry";wrapper.dataset.itemId=item.item_id;
  const bubble=document.createElement("div");bubble.className="msg user";
  const role=document.createElement("div");role.className="role";role.textContent=displayUserName(item);bubble.appendChild(role);
  bubble.appendChild(createMessageMeta(item));
  const content=document.createElement("div");content.className="message-content";content.textContent=item.content;bubble.appendChild(content);wrapper.appendChild(bubble);
  const actions=document.createElement("div");actions.className="message-actions";
  const siblings=branchSiblings(item);const index=siblings.findIndex(sibling=>sibling.item_id===item.item_id);
  if(siblings.length>1){
    const nav=document.createElement("span");nav.className="branch-nav";
    const previous=document.createElement("button");previous.type="button";previous.textContent="←";previous.title="Previous branch";previous.setAttribute("aria-label","Previous branch");previous.disabled=index<=0;previous.addEventListener("click",()=>selectBranchNode(siblings[index-1].item_id));nav.appendChild(previous);
    const count=document.createElement("span");count.className="branch-count";count.textContent=(index+1)+" / "+siblings.length;nav.appendChild(count);
    const next=document.createElement("button");next.type="button";next.textContent="→";next.title="Next branch";next.setAttribute("aria-label","Next branch");next.disabled=index<0||index>=siblings.length-1;next.addEventListener("click",()=>selectBranchNode(siblings[index+1].item_id));nav.appendChild(next);actions.appendChild(nav);
  }
  const regenerate=document.createElement("button");regenerate.type="button";regenerate.textContent="↻";regenerate.title="Regenerate response";regenerate.setAttribute("aria-label","Regenerate response");regenerate.addEventListener("click",()=>regenerateBranch(item));actions.appendChild(regenerate);
  const edit=document.createElement("button");edit.type="button";edit.textContent="Edit";edit.title="Edit message";edit.addEventListener("click",()=>editMessage(item,wrapper,content,actions));actions.appendChild(edit);
  wrapper.appendChild(actions);return wrapper;
}

function renderMarkdown(container,content){
  if(typeof marked==="undefined"||typeof DOMPurify==="undefined"){container.textContent=content||"";return}
  try{
    const parse=typeof marked.parse==="function"?marked.parse.bind(marked):marked;
    container.innerHTML=DOMPurify.sanitize(parse(content||"",{gfm:true,breaks:true}));
    for(const link of container.querySelectorAll("a[href]")){link.target="_blank";link.rel="noopener noreferrer"}
    for(const codeEl of container.querySelectorAll("pre code"))scheduleCodeHighlight(codeEl);
  }catch{container.textContent=content||""}
}

function addMessage(cls,content,role,item=null){
  const div=document.createElement("div");div.className="msg "+cls;
  if(role){const r=document.createElement("div");r.className="role";r.textContent=role;div.appendChild(r)}
  if(item)div.appendChild(createMessageMeta(item));
  const c=document.createElement("div");c.className="message-content";if(cls==="assistant")renderMarkdown(c,content);else c.textContent=content;div.appendChild(c);messagesEl.appendChild(div);return div;
}

function addReasoning(content){
  const details=document.createElement("details");details.className="msg reasoning";details.open=true;const summary=document.createElement("summary");summary.textContent="Reasoning";details.appendChild(summary);const c=document.createElement("div");c.className="message-content";renderMarkdown(c,content);details.appendChild(c);messagesEl.appendChild(details);return details;
}

function scheduleCodeHighlight(codeEl){
  if(codeEl._highlightScheduled)return;codeEl._highlightScheduled=true;
  const render=()=>{if(!document.body.contains(codeEl)){codeEl._highlightScheduled=false;return}if(typeof hljs==="undefined"){setTimeout(render,50);return}codeEl._highlightScheduled=false;delete codeEl.dataset.highlighted;hljs.highlightElement(codeEl)};
  requestAnimationFrame(render);
}

function createPrettyBlock(content,lang){
  const pre=document.createElement("pre");const codeEl=document.createElement("code");if(lang)codeEl.className="language-"+lang;let formatted=content;
  if(lang==="json"&&typeof content==="string")try{formatted=JSON.stringify(JSON.parse(content),null,2)}catch{}
  codeEl.textContent=formatted;pre.appendChild(codeEl);scheduleCodeHighlight(codeEl);return pre;
}

function showCodeActSpinner(){
  if(codeactSpinnerEl)return;codeactSpinnerEl=document.createElement("div");codeactSpinnerEl.className="typing";codeactSpinnerEl.innerHTML='<span class="codeact-spinner"></span>CodeAct session<span>.</span><span>.</span><span>.</span>';messagesEl.appendChild(codeactSpinnerEl);scrollToBottom();
}

function hideCodeActSpinner(){if(codeactSpinnerEl){codeactSpinnerEl.remove();codeactSpinnerEl=null}}

function addCodeActCall(args){
  let code;if(typeof args==="string"){try{const parsed=JSON.parse(args);code=parsed.code||args}catch{code=args}}else code=args&&typeof args.code==="string"?args.code:JSON.stringify(args,null,2);
  showCodeActSpinner();const details=document.createElement("details");details.className="msg codeact";details.open=true;const summary=document.createElement("summary");summary.textContent="CodeAct session";details.appendChild(summary);details.appendChild(createPrettyBlock(code,"python"));messagesEl.appendChild(details);codeactActiveEl=details;lastWasCodeAct=true;scrollToBottom();
}

function decodePartialCodeArg(raw){
  const key=raw.match(/"code"\s*:\s*"/);if(!key||key.index===undefined)return raw;let index=key.index+key[0].length;let result="";
  while(index<raw.length){const char=raw[index++];if(char==='"')return result;if(char!=="\\"){result+=char;continue}if(index>=raw.length)break;const escaped=raw[index++];if(escaped==="n")result+="\n";else if(escaped==="r")result+="\r";else if(escaped==="t")result+="\t";else if(escaped==="b")result+="\b";else if(escaped==="f")result+="\f";else if(escaped==="u"){const hex=raw.slice(index,index+4);if(hex.length<4||!/^[0-9a-fA-F]{4}$/.test(hex))break;result+=String.fromCharCode(parseInt(hex,16));index+=4}else if(escaped==='"'||escaped==="\\"||escaped==="/")result+=escaped;else result+=escaped}
  return result;
}

function codeActPreviewContent(raw){try{const parsed=JSON.parse(raw);if(parsed&&typeof parsed.code==="string")return parsed.code}catch{}return decodePartialCodeArg(raw)}

/** @param {StreamEvent} data */
function updateCodeActPreview(data){
  const meta=data.meta||{};if(meta.tool_name!=="execute")return false;const toolId=meta.tool_call_id||null;
  if(codeactStreamToolId&&toolId&&toolId!==codeactStreamToolId){codeactStreamArgs="";if(!document.body.contains(codeactActiveEl))codeactActiveEl=null}
  if(!codeactActiveEl)addCodeActCall({code:""});codeactStreamToolId=toolId;codeactStreamArgs+=data.content||"";const code=codeActPreviewContent(codeactStreamArgs);const codeEl=codeactActiveEl&&codeactActiveEl.querySelector("pre code");
  if(codeEl){codeEl.textContent=code;scheduleCodeHighlight(codeEl)}streamingPreviews.tool_call=codeactActiveEl;scrollToBottom();return true;
}

function finishCodeActSession(content){
  hideCodeActSpinner();if(codeactActiveEl){const spinner=codeactActiveEl.querySelector(".codeact-spinner");if(spinner)spinner.remove();const summary=codeactActiveEl.querySelector("summary");if(summary)summary.textContent="CodeAct session";codeactActiveEl=null}
  if(content){const details=document.createElement("details");details.className="msg tool-result";details.open=true;const summary=document.createElement("summary");summary.textContent="Result";details.appendChild(summary);details.appendChild(createPrettyBlock(content,null));messagesEl.appendChild(details);scrollToBottom()}
  codeactStreamArgs="";codeactStreamToolId=null;lastWasCodeAct=false;
}

function addToolCall(name,args){
  if(name==="execute"){addCodeActCall(args);return}const argsString=typeof args==="string"?args:JSON.stringify(args,null,2);const hasArgs=typeof args==="string"?args.length>0:Object.keys(args||{}).length>0;
  if(!hasArgs||!argsString.includes("\n")){const div=document.createElement("div");div.className="msg tool-call";const label=document.createElement("div");label.textContent="Tool: "+name;div.appendChild(label);if(hasArgs)div.appendChild(createPrettyBlock(argsString,"json"));messagesEl.appendChild(div);return}
  const details=document.createElement("details");details.className="msg tool-call";details.open=true;const summary=document.createElement("summary");summary.textContent="Tool: "+name;details.appendChild(summary);details.appendChild(createPrettyBlock(argsString,"json"));messagesEl.appendChild(details);
}

function addToolResult(content){
  const value=typeof content==="string"?content:JSON.stringify(content,null,2);
  if(!value.includes("\n")){const div=document.createElement("div");div.className="msg tool-result";const label=document.createElement("div");label.textContent="Tool Result";div.appendChild(label);div.appendChild(createPrettyBlock(value,null));messagesEl.appendChild(div);return}
  const details=document.createElement("details");details.className="msg tool-result";details.open=true;const summary=document.createElement("summary");summary.textContent="Tool Result";details.appendChild(summary);let lang=null;try{JSON.parse(value);lang="json"}catch{}details.appendChild(createPrettyBlock(value,lang));messagesEl.appendChild(details);
}

function addImageOutput(content){
  const div=document.createElement("div");div.className="msg image";try{const data=JSON.parse(content);if(data.url&&data.url.startsWith("data:image")){const image=document.createElement("img");image.src=data.url;image.style.maxWidth="300px";image.style.borderRadius="4px";div.appendChild(image)}else div.textContent="Image: "+content}catch{div.textContent="Image: "+content}messagesEl.appendChild(div);
}

function addFileOutput(content){
  const div=document.createElement("div");div.className="msg file";try{const data=JSON.parse(content);const icon=document.createElement("span");icon.className="icon";div.appendChild(icon);const span=document.createElement("span");span.textContent=(data.filename||data.name||data.path||"file")+(data.size?" ("+data.size+" bytes)":"");div.appendChild(span)}catch{const icon=document.createElement("span");icon.className="icon";div.appendChild(icon);const span=document.createElement("span");span.textContent=content;div.appendChild(span)}messagesEl.appendChild(div);
}

function addPlaceholder(type){const div=document.createElement("div");div.className="msg assistant";const placeholder=document.createElement("div");placeholder.className="placeholder";placeholder.textContent="["+type+"]";div.appendChild(placeholder);messagesEl.appendChild(div)}
function addError(text){addMessage("error",text,null)}

function showTyping(){
  if(typingIndicator)return;typingIndicator=document.createElement("div");typingIndicator.className="typing";typingIndicator.innerHTML="Thinking<span>.</span><span>.</span><span>.</span>";messagesEl.appendChild(typingIndicator);scrollToBottom();
}

function hideTyping(){if(typingIndicator){typingIndicator.remove();typingIndicator=null}}

function setProcessing(on,streamId=null){
  activeStreamId=on?streamId:null;sendBtn.textContent=on?"Cancel":"Send";sendBtn.classList.toggle("cancel",on);sendBtn.disabled=false;statusEl.textContent=on?"Processing...":"Ready";if(!on)hideTyping();syncActionState();
}

function syncActionState(){
  const busy=Boolean(activeStreamId);for(const button of document.querySelectorAll(".message-actions button, #new-branch-btn, .branch-row button"))button.disabled=busy;
}

/** @param {DialogItem} item */
function renderItem(item){
  hideTyping();
  const preview=streamingPreviews[item.item_type];if(preview){preview.remove();delete streamingPreviews[item.item_type]}
  for(const key of Object.keys(activeStreams)){const stream=activeStreams[key];if(stream.item_type===item.item_type&&stream.previous_item_id===item.previous_item_id){stream.element.remove();delete activeStreams[key]}}
  switch(item.item_type){
    case "input":
    case "image_input":
    case "file_input":
      if(item.role==="user")messagesEl.appendChild(createUserEntry(item));else addPlaceholder(item.item_type);break;
    case "reasoning":addReasoning(item.content);break;
    case "tool_call":try{const toolCall=JSON.parse(item.content);addToolCall(toolCall.tool_name||"unknown",toolCall.tool_args||{})}catch{addToolCall("tool",item.content)}break;
    case "tool_call_result":if(lastWasCodeAct){try{const result=JSON.parse(item.content);finishCodeActSession(result.content)}catch{finishCodeActSession(item.content)}}else{try{const result=JSON.parse(item.content);addToolResult(result.content)}catch{addToolResult(item.content)}}break;
    case "image_output":addImageOutput(item.content);break;
    case "file_output":addFileOutput(item.content);break;
    default:addMessage("assistant",item.content,"Assistant",item);
  }
}

/** @param {StreamEvent} data */
function handleStreamChunk(data){
  if(selectedHeadId!==null&&data.previous_item_id!==null&&data.previous_item_id!==selectedHeadId)return;
  hideTyping();const chunkType=data.item_type||"output";
  if(chunkType==="tool_call"&&updateCodeActPreview(data))return;
  const streamId=data.stream_id||chunkType;let stream=activeStreams[streamId];
  statusEl.textContent="Streaming...";
  if(!stream){let element;if(chunkType==="reasoning")element=addReasoning("");else if(chunkType==="tool_call"){element=document.createElement("details");element.className="msg tool-call";element.open=true;const summary=document.createElement("summary");summary.textContent="Tool: ...";element.appendChild(summary);const content=document.createElement("div");element.appendChild(content);messagesEl.appendChild(element)}else element=addMessage("assistant","","Assistant");stream={element,item_type:chunkType,previous_item_id:data.previous_item_id,text:""};activeStreams[streamId]=stream}
  stream.text+=(data.content||"");const contentEl=stream.element.querySelector("div:last-child")||stream.element;
  if(chunkType==="output"||chunkType==="reasoning")renderMarkdown(contentEl,stream.text);else contentEl.textContent=stream.text;
  scrollToBottom();
}

async function submitMessage(text,parentId,branch=null){
  if(!authToken){showAuth();return false}
  if(activeStreamId)return false;
  const previousItemId=parentId===null||parentId===undefined?null:parentId;
  debug("submit message",{previousItemId,selectedHeadId,newRootSelected,historyLoaded,branch: Boolean(branch),contentLength:text.length});
  pendingBranch=branch;pendingMessage={parentId:previousItemId,content:text};pendingRoot=!branch&&previousItemId===null;pendingRootContent=pendingRoot?text:"";statusEl.textContent="Sending...";sendBtn.disabled=true;
  try{
    const response=await authFetch("/api/messages?stream=1",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:text,previous_item_id:previousItemId,timezone:browserTimezone()})});
    if(response.status===401){setProcessing(false);clearAuth();showAuth("Your session has expired. Sign in again.");pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";return false}
    if(!response.ok){setProcessing(false);const data=await response.json().catch(()=>({}));addError(data.error||data.detail||"Message was rejected");pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";return false}
    const data=await response.json();setProcessing(true,data.stream_id);showTyping();return true;
  }catch(error){addError("Network error: "+error.message);pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";setProcessing(false);return false}
}

async function send(){
  const text=inputEl.value.trim();if(!text||activeStreamId)return;
  inputEl.value="";inputEl.style.height="auto";
  const fallbackParentId=latestGlobalVisibleId();
  const parentId=newRootSelected?null:(selectedHeadId??fallbackParentId);
  debug("send selected parent",{selectedHeadId,newRootSelected,fallbackParentId,parentId,historyLoaded});
  const sent=await submitMessage(text,parentId,null);if(!sent){inputEl.value=text;adjustInputHeight()}
}

async function cancelProcessing(){
  const streamId=activeStreamId;if(!streamId)return;
  setProcessing(false);
  try{
    const response=await authFetch("/api/messages/"+streamId,{method:"DELETE"});
    if(response.status===401){clearAuth();showAuth("Your session has expired. Sign in again.")}
  }catch(error){addError("Cancel request failed: "+error.message)}
}

/** @param {DialogItem} item */
async function regenerateBranch(item){
  const sent=await submitMessage(item.content,item.previous_item_id,{parentId:item.previous_item_id,content:item.content});
  if(sent)closeBranchPanel();
}

/**
 * @param {DialogItem} item
 * @param {HTMLElement} wrapper
 * @param {HTMLElement} content
 * @param {HTMLElement} actions
 */
function editMessage(item,wrapper,content,actions){
  if(activeStreamId||wrapper.dataset.editing==="true")return;wrapper.dataset.editing="true";content.replaceChildren();
  const textarea=document.createElement("textarea");textarea.className="message-edit";textarea.value=item.content;content.appendChild(textarea);
  actions.replaceChildren();const editActions=document.createElement("div");editActions.className="edit-actions";
  const cancel=document.createElement("button");cancel.type="button";cancel.textContent="Cancel";cancel.addEventListener("click",()=>renderHistory());editActions.appendChild(cancel);
  const save=document.createElement("button");save.type="button";save.className="primary";save.textContent="Save";save.addEventListener("click",async()=>{const text=textarea.value.trim();if(!text){textarea.focus();return}save.disabled=true;cancel.disabled=true;const sent=await submitMessage(text,item.previous_item_id,{parentId:item.previous_item_id,content:text});if(!sent){save.disabled=false;cancel.disabled=false}else closeBranchPanel()});editActions.appendChild(save);content.appendChild(editActions);textarea.focus();textarea.setSelectionRange(textarea.value.length,textarea.value.length);
  textarea.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==="Enter"){event.preventDefault();save.click()}});
}

function newBranch(){
  if(activeStreamId)return;
  newRootSelected=true;selectedHeadId=null;
  debug("new root selected",{historyLoaded,latestVisibleId:latestGlobalVisibleId()});
  pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent="";renderHistory();inputEl.focus();closeBranchPanel();
}

/** @param {StreamEvent} data */
async function handleServerEvent(data){
  if(data.type==="stream_chunk")handleStreamChunk(data);
  else if(data.type==="dialog_item")await applyDialogItem(data);
  else if(data.type==="typing"){
    if(data.active){showTyping();statusEl.textContent="Processing..."}else hideTyping();
  }
  else if(data.type==="message_done"){if(!activeStreamId||data.stream_id===activeStreamId)setProcessing(false)}
  else if(data.type==="error")addError(data.content||data.error||"Server error");
}

async function loadHistory(preferredHeadId=null){
  const knownItemIds=new Set(itemsById.keys());
  debug("load history start",{selectedHeadId,newRootSelected,historyLoaded,knownItems:knownItemIds.size,pendingParentId:pendingMessage?.parentId,preferredHeadId});
  const response=await authFetch("/api/history");
  if(response.status===401){clearAuth();showAuth("Your session has expired. Sign in again.");return}
  if(!response.ok)throw new Error("History request failed");
  const data=await response.json();const previousSelected=selectedHeadId;rebuildGraph(data.items||[]);
  const preferredItem=typeof preferredHeadId==="number"?itemsById.get(preferredHeadId):null;
  const preferredContinuesSelection=Boolean(preferredItem&&((selectedHeadId!==null&&chainContains(preferredItem.item_id,selectedHeadId))||(selectedHeadId===null&&!newRootSelected)));
  debug("history loaded",{items:(data.items||[]).length,opaque:(data.items||[]).filter(isOpaqueItem).length,visibleRoots:visibleRoots().map(item=>item.item_id),previousSelected,newRootSelected,preferredContinuesSelection});
  const pendingItem=pendingMessage?[...itemsById.values()].filter(item=>!knownItemIds.has(item.item_id)&&isUserItem(item)&&item.previous_item_id===pendingMessage.parentId&&item.content===pendingMessage.content).sort(compareItems).pop():null;
  const keepSelection=historyLoaded&&!pendingMessage&&previousSelected!==null&&isVisibleItem(itemsById.get(previousSelected));
  if(pendingItem){selectedHeadId=latestVisibleItemId(pendingItem.item_id)||pendingItem.item_id;pendingMessage=null;pendingBranch=null;pendingRoot=false;pendingRootContent=""}else if(preferredContinuesSelection&&preferredItem)selectedHeadId=latestVisibleItemId(preferredItem.item_id)||preferredItem.item_id;else if(keepSelection)selectedHeadId=previousSelected;else if(!historyLoaded&&!pendingMessage)selectedHeadId=latestGlobalVisibleId();else if(!pendingMessage&&selectedHeadId!==null&&!itemsById.has(selectedHeadId))selectedHeadId=latestGlobalVisibleId();
  historyLoaded=true;debug("history selection",{selectedHeadId,newRootSelected,visible:selectedVisibleId(),chain:currentChain().map(item=>({itemId:item.item_id,previousItemId:item.previous_item_id,opaque:isOpaqueItem(item)}))});rememberCurrentSelection();renderHistory();
}

async function handleEventStream(response){
  if(!response.body)throw new Error("Events stream has no body");
  const reader=response.body.getReader();currentReader=reader;const decoder=new TextDecoder();let buffer="";let ended=false;
  try{
    while(authToken){const result=await reader.read();if(result.done){ended=true;break}buffer+=decoder.decode(result.value,{stream:true});const lines=buffer.split("\n");buffer=lines.pop();for(const line of lines){if(!line.startsWith("data: "))continue;try{const data=JSON.parse(line.slice(6));if(data.type!=="done")await handleServerEvent(data)}catch{}}}
  }
  finally{if(!ended)await reader.cancel().catch(()=>{});if(currentReader===reader)currentReader=null}
}

async function eventsLoop(){
  while(authToken){
    try{
      eventsAbortController=new AbortController();const response=await authFetch("/api/events",{signal:eventsAbortController.signal});
      if(response.status===401){clearAuth();showAuth("Your session has expired. Sign in again.");return}
      if(!response.ok){await new Promise(resolve=>setTimeout(resolve,1000));continue}
      await loadHistory();await handleEventStream(response);
    }catch(error){if(!authToken||error.name==="AbortError")return;await new Promise(resolve=>setTimeout(resolve,1000))}
    finally{eventsAbortController=null}
  }
}

function startEvents(){if(!eventsTask)eventsTask=eventsLoop().finally(()=>{eventsTask=null})}

async function loadCurrentUser(){
  debug("load current user",{hasToken:Boolean(authToken)});
  if(!authToken){showAuth();return false}
  const response=await authFetch("/api/me");
  debug("current user response",{status:response.status});
  if(!response.ok){clearAuth();showAuth();return false}
  applyUser(await response.json());
  try{await loadHistory()}catch(error){addError("Could not load history: "+error.message)}
  startEvents();
  return true;
}

function logout(){clearAuth();showAuth()}
function scrollToBottom(){requestAnimationFrame(()=>{messagesEl.scrollTop=messagesEl.scrollHeight})}
function closeBranchPanel(){document.body.classList.remove("branch-panel-open")}
function openBranchPanel(){document.body.classList.add("branch-panel-open")}
function adjustInputHeight(){inputEl.style.height="auto";const maxHeight=window.innerHeight*.33;inputEl.style.height=Math.min(inputEl.scrollHeight,maxHeight)+"px"}

function setupPasswordToggle(button){
  const input=document.getElementById(button.dataset.passwordTarget);
  if(!input){debug("password toggle target missing",{target:button.dataset.passwordTarget});return}
  debug("password toggle ready",{target:input.id});
  button.addEventListener("click",()=>{const visible=input.type==="text";input.type=visible?"password":"text";button.textContent=visible?"Show":"Hide";button.setAttribute("aria-pressed",String(!visible));debug("password visibility changed",{target:input.id,visible:!visible})});
}

async function registerOrLogin(event){
  event.preventDefault();const username=authUsername.value.trim();const password=authPassword.value;authError.textContent="";debug("auth submit started",{mode:authMode,username});
  if(!username||!password){authError.textContent="Username and password are required";return}
  if(authMode==="register"&&password!==authConfirm.value){authError.textContent="Passwords do not match";return}
  authSubmit.disabled=true;
  try{
    if(authMode==="register"){
      const response=await fetch("/api/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:inviteToken,username,password})});debug("register response",{status:response.status});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=data.detail||"Registration failed";return}history.replaceState({},"",location.pathname);inviteToken=null;authMode="login";setAuthMode("login");authUsername.value=username;authPassword.value="";authError.textContent="Account created. Sign in with your new password.";return;
    }
    const response=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});debug("login response",{status:response.status});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=data.detail||"Sign in failed";return}authToken=data.access_token;localStorage.setItem("commamatrix_auth_token",authToken);debug("login token stored");await loadCurrentUser();authForm.reset();
  }catch(error){console.error("[CommaMatrix UI] auth request failed",error);authError.textContent="Network error: "+error.message}finally{authSubmit.disabled=false}
}

document.querySelectorAll(".password-toggle").forEach(setupPasswordToggle);
authSubmit.addEventListener("click",()=>{debug("auth button clicked");void registerOrLogin({preventDefault(){}})});
passwordBtn.addEventListener("click",()=>{passwordError.textContent="";passwordForm.reset();passwordOverlay.classList.remove("hidden")});
document.getElementById("password-cancel").addEventListener("click",()=>passwordOverlay.classList.add("hidden"));
passwordForm.addEventListener("submit",async event=>{event.preventDefault();passwordError.textContent="";const next=document.getElementById("new-password").value;if(next!==document.getElementById("new-password-confirm").value){passwordError.textContent="Passwords do not match";return}try{const response=await authFetch("/api/password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({old_password:document.getElementById("old-password").value,new_password:next})});const data=await response.json().catch(()=>({}));if(response.status===401){logout();return}if(!response.ok){passwordError.textContent=data.detail||"Password change failed";return}passwordOverlay.classList.add("hidden")}catch(error){passwordError.textContent="Network error: "+error.message}});
inviteBtn.addEventListener("click",async()=>{const response=await authFetch("/api/invite",{method:"POST"});const data=await response.json().catch(()=>({}));if(response.status===401){logout();return}if(!response.ok){addError(data.detail||"Could not create invitation");return}inviteUrl.textContent=data.url;inviteOverlay.classList.remove("hidden")});
document.getElementById("invite-copy").addEventListener("click",async function(){await navigator.clipboard.writeText(inviteUrl.textContent);this.textContent="Copied";setTimeout(()=>{this.textContent="Copy link"},1200)});
document.getElementById("invite-close").addEventListener("click",()=>inviteOverlay.classList.add("hidden"));
logoutBtn.addEventListener("click",logout);authForm.addEventListener("submit",event=>{debug("auth form submitted");void registerOrLogin(event)});authForm.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();debug("auth form enter pressed");void registerOrLogin(event)}});sendBtn.addEventListener("click",()=>{if(activeStreamId)void cancelProcessing();else void send()});newBranchBtn.addEventListener("click",newBranch);activeBranchesBtn.addEventListener("click",()=>setBranchView(false));deletedBranchesBtn.addEventListener("click",()=>setBranchView(true));branchOpenBtn.addEventListener("click",openBranchPanel);branchCloseBtn.addEventListener("click",closeBranchPanel);branchBackdrop.addEventListener("click",closeBranchPanel);
inputEl.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();void send()}});inputEl.addEventListener("input",adjustInputHeight);window.addEventListener("resize",adjustInputHeight);

debug("auth controls initialized",{form:Boolean(authForm),button:Boolean(authSubmit),username:Boolean(authUsername),password:Boolean(authPassword)});setAuthMode(authMode);renderBranchPanel();if(inviteToken){clearAuth();showAuth()}else void loadCurrentUser();
})();
