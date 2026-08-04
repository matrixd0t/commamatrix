// builtin/http_connector/ui/app.js
/** @typedef {{origin_type?: string, platform?: string, http_user_id?: number}} DialogOrigin */
/** @typedef {{item_id: number|null, previous_item_id: number|null, item_type?: string, role?: string, content?: string, user?: string, origin?: DialogOrigin, created_at?: string|null, external_id?: string|null, meta?: Record<string, unknown>}} DialogItem */
/** @typedef {{tool_name?: string, tool_call_id?: string}} StreamMeta */
/** @typedef {{type?: string, item_id?: number|null, item_type?: string, role?: string, content?: string, error?: string, active?: boolean, previous_item_id?: number|null, stream_id?: string|null, meta?: StreamMeta}} StreamEvent */
/* global hljs, marked, DOMPurify */
(function(){
"use strict";

const SERVER_ROOT="/commamatrix";
function serverUrl(path){return SERVER_ROOT+path}
window.__commamatrixUiLoaded=true;
window.addEventListener("error",event=>{console.error("[CommaMatrix UI] uncaught error",event.error||event.message);const error=document.getElementById("auth-error");if(error)error.textContent="Interface error: "+event.message});
window.addEventListener("unhandledrejection",event=>{console.error("[CommaMatrix UI] unhandled rejection",event.reason);const error=document.getElementById("auth-error");if(error)error.textContent="Interface error: "+(event.reason?.message||event.reason||"Unknown error")});

const messagesEl=document.getElementById("messages");
const inputEl=document.getElementById("input");
const fileInput=document.getElementById("file-input");
const attachBtn=document.getElementById("attach-btn");
const inputArea=document.getElementById("input-area");
const dropOverlay=document.getElementById("drop-overlay");
const attachmentPreviewsEl=document.getElementById("attachment-previews");
const sendBtn=document.getElementById("send-btn");
const statusEl=document.getElementById("status");
const serverStatusBtn=document.getElementById("http-server-status-btn");
const serverStatusLight=document.getElementById("http-server-status-light");
const serverStatusPanel=document.getElementById("http-server-status-panel");
const userLabel=document.getElementById("user-label");
const headerMenuBtn=document.getElementById("header-menu-btn");
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
const attachmentOverlay=document.getElementById("attachment-overlay");
const insertLinkChoice=document.getElementById("insert-link-choice");
const uploadFileChoice=document.getElementById("upload-file-choice");
const attachmentCancel=document.getElementById("attachment-cancel");
const linkOverlay=document.getElementById("link-overlay");
const linkForm=document.getElementById("link-form");
const linkInput=document.getElementById("link-input");
const linkError=document.getElementById("link-error");
const linkCancel=document.getElementById("link-cancel");

let inviteToken=new URLSearchParams(location.search).get("token");
let authToken=localStorage.getItem("commamatrix_auth_token");
let currentUser=null;
let authMode=inviteToken?"register":"login";
let activeStreamId=null;
let eventsTask=null;
let eventsAbortController=null;
let currentReader=null;
let eventsReady=false;
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
let pendingAttachments=[];
let pageDragDepth=0;
let pendingRoot=false;
let pendingRootContent="";
let historyLoaded=false;
let fileUploadAllowed=false;
let serverStatusMessages=[];
let statusPollTimer=null;
let statusPanelOverride=null;
let statusOverrideTimer=null;
let serverConnected=null;
const STATUS_POLL_INTERVAL_MS=10000;
const NO_PUBLIC_ADDRESS_MESSAGE="You cannot upload files for LLM: CommaMatrix is not visible from the Internet.";

function updateSendButton(){
  sendBtn.disabled=!currentUser||document.body.classList.contains("auth-locked")||(!activeStreamId&&!eventsReady);
}

function setEventsReady(ready){
  eventsReady=ready;updateSendButton();
  if(authToken&&!activeStreamId)setUiStatus(ready?"Ready":"Connecting...");
}

function setAuthLocked(locked){
  document.body.classList.toggle("auth-locked",locked);
  updateSendButton();
  if(locked){authOverlay.classList.remove("hidden");authOverlay.style.display="flex"}
  else{authOverlay.classList.add("hidden");authOverlay.style.display="none"}
}

function setHeaderMenuOpen(open){
  document.body.classList.toggle("header-menu-open",open);
  headerMenuBtn.setAttribute("aria-expanded",String(open));
  headerMenuBtn.setAttribute("aria-label",open?"Close account menu":"Open account menu");
  headerMenuBtn.title=open?"Close account menu":"Open account menu";
}

function setStatusPanelVisible(visible){
  serverStatusPanel.classList.toggle("visible",visible);
  serverStatusBtn.setAttribute("aria-expanded",String(visible));
}

function renderServerStatusMessages(){
  const messages=statusPanelOverride?[statusPanelOverride]:serverStatusMessages;
  serverStatusPanel.replaceChildren();
  for(const item of messages){
    const message=document.createElement("div");message.className="http-server-status-message "+item.severity;message.textContent=item.message;serverStatusPanel.appendChild(message);
  }
}

function statusKind(text){
  const value=String(text||"").toLowerCase();
  if(value.includes("disconnect"))return "disconnected";
  if(value.includes("connect"))return "connecting";
  if(value.includes("process")||value.includes("stream")||value.includes("send"))return "processing";
  if(value==="ready")return "ready";
  return "";
}
function setUiStatus(text){
  const value=serverConnected===false?"Disconnected":text;
  const kind=statusKind(value);statusEl.textContent=value;statusEl.className="status"+(kind?" status-"+kind:"");
}
function serverStatusSeverity(){return serverStatusMessages.some(item=>item.severity==="red")?"red":serverStatusMessages.length?"yellow":"green"}
function updateServerStatusLight(){const severity=serverConnected===false?"gray":statusPanelOverride?.severity||serverStatusSeverity();serverStatusLight.className="http-server-status-light "+severity}
function setServerConnected(connected){
  const wasDisconnected=serverConnected===false;serverConnected=connected;updateServerStatusLight();
  if(!connected)setUiStatus("Disconnected");else if(wasDisconnected)setUiStatus(eventsReady?"Ready":"Connecting...");
}

function updateServerStatus(data){
  serverStatusMessages=Array.isArray(data.messages)?data.messages.filter(item=>item&&typeof item.message==="string"&&["yellow","red"].includes(item.severity)).map(item=>({message:item.message,severity:item.severity})):[];
  fileUploadAllowed=data.file_upload_allowed===true;
  uploadFileChoice.disabled=!fileUploadAllowed;
  uploadFileChoice.title=fileUploadAllowed?"Upload a file":"File uploads require a public http-server address";
  setServerConnected(true);
  renderServerStatusMessages();
}

function showTemporaryStatus(message,severity="yellow"){
  statusPanelOverride={message,severity};
  updateServerStatusLight();
  renderServerStatusMessages();setStatusPanelVisible(true);
  if(statusOverrideTimer)clearTimeout(statusOverrideTimer);
  statusOverrideTimer=setTimeout(()=>{statusPanelOverride=null;statusOverrideTimer=null;updateServerStatusLight();renderServerStatusMessages();setStatusPanelVisible(false)},5000);
}

function showUploadBlocked(){showTemporaryStatus(NO_PUBLIC_ADDRESS_MESSAGE);}

function stopStatusPolling(){if(statusPollTimer){clearInterval(statusPollTimer);statusPollTimer=null}if(statusOverrideTimer){clearTimeout(statusOverrideTimer);statusOverrideTimer=null}}

async function pollServerStatus(){
  if(!authToken)return;
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/api/status"));
    if(!authToken||unauthorized)return;
    if(response.ok)updateServerStatus(data);
    else{fileUploadAllowed=false;uploadFileChoice.disabled=true;setServerConnected(false)}
  }catch{fileUploadAllowed=false;uploadFileChoice.disabled=true;setServerConnected(false)}
}

function startStatusPolling(){
  stopStatusPolling();
  void pollServerStatus();
  statusPollTimer=setInterval(()=>{void pollServerStatus()},STATUS_POLL_INTERVAL_MS);
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
}

function authHeaders(){return authToken?{Authorization:"Bearer "+authToken}:{};}

function browserTimezone(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone||"UTC"}catch{return "UTC"}}

function formatFileSize(size){if(!Number.isFinite(Number(size))||Number(size)<0)return "";const value=Number(size);if(value<1024)return value+" B";if(value<1024*1024)return (value/1024).toFixed(1)+" KB";if(value<1024*1024*1024)return (value/1024/1024).toFixed(1)+" MB";return (value/1024/1024/1024).toFixed(1)+" GB"}

function isDirectResource(url){return typeof url==="string"&&(/^(data|https?|blob):/i.test(url))}
function fileContentUrl(ref){return typeof ref==="string"&&ref?serverUrl("/files/")+encodeURIComponent(ref):null}

function parseAttachmentContent(content){
  let data;try{data=typeof content==="string"?JSON.parse(content):content}catch{return null}
  if(!data||typeof data!=="object")return null;
  const kind=data.image?"image":data.file?"file":data.type==="image"?"image":data.type==="file"?"file":null;
  const value=(kind&&data[kind]&&typeof data[kind]==="object")?data[kind]:data;
  const ref=value.ref||value.file_id||value.id||null;
  const url=value.url||value["content_url"]||null;
  if(!ref&&!url&&!value.name&&!value.filename&&!value.path)return null;
  return {kind:kind||((value.mime_type||"").startsWith("image/")?"image":"file"),ref,name:value.name||value.filename||value.path||ref||"file",mime_type:value.mime_type||"",size:value.size,ext:value.ext||"",url,previewUrl:value.previewUrl||null}
}

function attachmentResourceUrl(info){
  const candidate=info.previewUrl||info.url;
  if(typeof candidate==="string"&&candidate){
    if(candidate.startsWith(SERVER_ROOT+"/"))return candidate;
    if(candidate.startsWith("/"))return serverUrl(candidate);
    return candidate;
  }
  return fileContentUrl(info.ref);
}

async function protectedResourceUrl(url){
  if(!url||isDirectResource(url))return url;
  const response=await authFetch(url);
  if(isUnauthorized(response))throw new Error("Authentication required")
  if(!response.ok)throw new Error("File request failed")
  return URL.createObjectURL(await response.blob());
}

function setResource(element,resource,property,onError){
  if(!resource)return;
  if(isDirectResource(resource)){element[property]=resource;return}
  void protectedResourceUrl(resource).then(url=>{if(url)element[property]=url}).catch(onError);
}

function createAttachmentCard(info,{compact=false}={}){
  const card=document.createElement("div");card.className="attachment-card"+(info.kind==="image"?" image-card":"")+(compact?" compact":"");
  const resource=attachmentResourceUrl(info);
  if(info.kind==="image"&&!info.error){
    const image=document.createElement("img");image.alt=info.name||"Image";card.appendChild(image);
    setResource(image,resource,"src",()=>{image.alt="Image unavailable"})
  }else{
    const icon=document.createElement("span");icon.className="attachment-icon";icon.textContent=info.kind==="image"?"IMAGE":"FILE";card.appendChild(icon);
  }
  const details=document.createElement("span");details.className="attachment-info";
  if(info.kind!=="image"&&!info.error){
    const link=document.createElement("a");link.className="attachment-name";link.textContent=info.name||"File";link.download=info.name||"file";link.rel="noopener noreferrer";
    setResource(link,resource,"href",()=>{link.textContent=(info.name||"File")+" (unavailable)"})
    details.appendChild(link);
  }else{const name=document.createElement("span");name.className="attachment-name";name.textContent=info.name||(info.kind==="image"?"Image":"File");details.appendChild(name)}
  if(info.size!==undefined&&info.size!==null){const size=document.createElement("span");size.className="attachment-size";size.textContent=formatFileSize(info.size);details.appendChild(size)}
  if(info.error){const error=document.createElement("span");error.className="attachment-error";error.textContent=info.error;details.appendChild(error)}
  card.appendChild(details);return card;
}

function addAttachmentMessage(content,kind){
  const div=document.createElement("div");div.className="msg "+(kind==="image"?"image":"file");const info=parseAttachmentContent(content);
  if(info&&(info.ref||info.url||kind==="file")){info.kind=kind||info.kind;div.appendChild(createAttachmentCard(info))}else div.textContent=kind==="image"?"Image: "+content:"File: "+content;
  messagesEl.appendChild(div);scrollToBottom();return div;
}

function outputAttachments(item){
  const attachments=item?.meta?.http?.attachments;
  return Array.isArray(attachments)?attachments.filter(attachment=>attachment&&typeof attachment==="object"):[];
}

function addAssistantOutput(item){
  const wrapper=document.createElement("div");wrapper.className="message-entry assistant-entry";wrapper.dataset.itemId=String(item.item_id??"");
  const bubble=document.createElement("div");bubble.className="msg assistant";
  const role=document.createElement("div");role.className="role";role.textContent="Assistant";bubble.appendChild(role);
  bubble.appendChild(createMessageMeta(item));
  if(item.content){const content=document.createElement("div");content.className="message-content";renderMarkdown(content,item.content);bubble.appendChild(content)}
  const attachments=outputAttachments(item);
  if(attachments.length){const list=document.createElement("div");list.className="message-attachments";for(const attachment of attachments)list.appendChild(createAttachmentCard(attachment));bubble.appendChild(list)}
  wrapper.appendChild(bubble);messagesEl.appendChild(wrapper);return wrapper;
}

function attachmentPayload(attachment){
  const payload={type:attachment.kind,filename:attachment.name,mime_type:attachment.mime_type,ext:attachment.ext};
  if(attachment.external)payload.url=attachment.url;else payload.file_id=attachment.file_id;
  return payload;
}

function renderAttachmentPreviews(){
  attachmentPreviewsEl.replaceChildren();
  for(const attachment of pendingAttachments){
    const preview=document.createElement("div");preview.className="attachment-preview "+(attachment.status||"")+(attachment.external?" external":"");
    if(attachment.kind==="image"&&attachment.previewUrl){const image=document.createElement("img");image.src=attachment.previewUrl;image.alt=attachment.name;preview.appendChild(image)}else{const icon=document.createElement("span");icon.className="attachment-icon";icon.textContent=attachment.external?"LINK":"FILE";preview.appendChild(icon)}
    const details=document.createElement("span");details.className="attachment-info";const name=document.createElement("span");name.className="attachment-name";name.textContent=attachment.name;details.appendChild(name);const status=document.createElement("span");status.className="attachment-status";status.textContent=attachment.status==="uploading"?"Uploading...":attachment.status==="failed"?attachment.error||"Upload failed":attachment.external?"External link":formatFileSize(attachment.size)||"Ready";details.appendChild(status);preview.appendChild(details);
    const remove=document.createElement("button");remove.type="button";remove.className="attachment-remove";remove.textContent="×";remove.title="Remove attachment";remove.setAttribute("aria-label","Remove "+attachment.name);remove.addEventListener("click",()=>removePendingAttachment(attachment));preview.appendChild(remove);attachmentPreviewsEl.appendChild(preview);
  }
}

function releasePreviewUrl(attachment){if(typeof attachment.previewUrl==="string"&&attachment.previewUrl.startsWith("blob:"))URL.revokeObjectURL(attachment.previewUrl)}
function removePendingAttachment(attachment){const index=pendingAttachments.indexOf(attachment);if(index<0)return;releasePreviewUrl(attachment);pendingAttachments.splice(index,1);renderAttachmentPreviews()}
function clearPendingAttachments(){for(const attachment of pendingAttachments)releasePreviewUrl(attachment);pendingAttachments=[];if(attachmentPreviewsEl)renderAttachmentPreviews()}

function externalLinkAttachment(url){
  let name="External link";let ext="";let kind="file";let mime_type="application/octet-stream";
  try{
    const parsed=new URL(url);const pathName=decodeURIComponent(parsed.pathname.split("/").pop()||"");if(pathName)name=pathName;else if(parsed.hostname)name=parsed.hostname;
    ext=(pathName.match(/\.([a-z0-9]+)$/i)?.[1]||"").toLowerCase();
    const imageMime={gif:"image/gif",jpeg:"image/jpeg",jpg:"image/jpeg",png:"image/png",svg:"image/svg+xml",webp:"image/webp",avif:"image/avif",bmp:"image/bmp"}[ext];
    if(imageMime){kind="image";mime_type=imageMime}
  }catch{}
  return {external:true,url,previewUrl:url,name,mime_type,ext,kind,status:"ready"};
}

function addExternalLink(url){pendingAttachments.push(externalLinkAttachment(url));renderAttachmentPreviews();setUiStatus("Ready")}

async function uploadFile(file){
  if(!authToken){showAuth();return false}
  if(!fileUploadAllowed){showUploadBlocked();return false}
  const attachment={name:file.name||"file",size:file.size,mime_type:file.type||"application/octet-stream",kind:(file.type||"").startsWith("image/")?"image":"file",status:"uploading",previewUrl:URL.createObjectURL(file)};pendingAttachments.push(attachment);renderAttachmentPreviews();
  const form=new FormData();form.append("file",file,attachment.name);form.append("purpose","user_data");
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/v1/files"),{method:"POST",body:form});
    if(unauthorized)return false
    if(!response.ok){attachment.status="failed";attachment.error=data.error||data.detail||"Upload failed";renderAttachmentPreviews();return false}
    attachment.file_id=data.id||data.file_id;attachment.name=data.filename||data.name||attachment.name;attachment.mime_type=data.mime_type||attachment.mime_type;attachment.size=data.bytes??data.size_bytes??attachment.size;attachment.kind=attachment.mime_type.startsWith("image/")?"image":attachment.kind;attachment.url=data.content_url||data.url||fileContentUrl(attachment.file_id);attachment.ext=attachment.name.includes(".")?attachment.name.split(".").pop().toLowerCase():"";attachment.status="ready";
  }catch(error){attachment.status="failed";attachment.error=error.message||"Upload failed"}
  renderAttachmentPreviews();return attachment.status==="ready";
}

function uploadFiles(files){
  const values=Array.from(files||[]);if(!values.length)return;
  if(!fileUploadAllowed){showUploadBlocked();return}
  for(const file of values)void uploadFile(file)
}
function hasDraggedContent(event){const transfer=event.dataTransfer;if(!transfer)return false;const types=Array.from(transfer.types||[]);return Boolean(transfer.files?.length||types.some(type=>["Files","text/uri-list","text/html","text/plain"].includes(type)))}
function readTransferData(transfer,type){try{return transfer.getData(type)||""}catch{return ""}}
function httpUrl(value){try{const raw=value.trim();const url=new URL(raw);return ["http:","https:"].includes(url.protocol)?raw:null}catch{return null}}
function droppedUrl(event){
  const transfer=event.dataTransfer;if(!transfer)return null;
  const uriList=readTransferData(transfer,"text/uri-list");
  for(const line of uriList.split(/\r?\n/)){const url=httpUrl(line.replace(/^#.*$/,""));if(url)return url}
  const plainUrl=httpUrl(readTransferData(transfer,"text/plain"));if(plainUrl)return plainUrl;
  const html=readTransferData(transfer,"text/html");if(html){try{const doc=new DOMParser().parseFromString(html,"text/html");const link=doc.querySelector("a")?.getAttribute("href")||doc.querySelector("img")?.getAttribute("src");const url=httpUrl(link||"");if(url)return url}catch{}}
  return null;
}
function insertDroppedUrl(url){addExternalLink(url)}
function setDropActive(active){inputArea.classList.toggle("drag-over",active);dropOverlay.setAttribute("aria-hidden",String(!active))}
function resetPageDrag(){pageDragDepth=0;setDropActive(false)}
function handlePageDragEnter(event){if(!hasDraggedContent(event))return;event.preventDefault();pageDragDepth+=1;setDropActive(true)}
function handlePageDragOver(event){if(!hasDraggedContent(event))return;event.preventDefault();event.dataTransfer.dropEffect="copy";setDropActive(true)}
function handlePageDragLeave(event){if(!pageDragDepth)return;event.preventDefault();pageDragDepth=Math.max(0,pageDragDepth-1);if(!pageDragDepth)setDropActive(false)}
function handlePageDrop(event){event.preventDefault();resetPageDrag()}
function handleDrop(event){
  event.preventDefault();resetPageDrag();
  const url=droppedUrl(event);if(url){insertDroppedUrl(url);return}
  const files=event.dataTransfer?.files;if(files?.length)uploadFiles(files);else if(!fileUploadAllowed)showUploadBlocked();
}

function pendingItemMatches(item){
  if(!pendingMessage||!isUserItem(item)||item.previous_item_id!==pendingMessage.parentId)return false;
  if(item.item_type==="input"&&item.content===pendingMessage.content)return true;
  const info=parseAttachmentContent(item.content);return Boolean(info&&pendingMessage.attachments?.some(attachment=>attachment.external?attachment.url===info.url:attachment.file_id===info.ref));
}

async function authFetch(url,options={}){
  const headers={...authHeaders(),...(options.headers||{})};
  return fetch(url,{...options,headers});
}

function expireSession(){clearAuth();showAuth("Your session has expired. Sign in again.")}
function isUnauthorized(response){if(response.status!==401)return false;expireSession();return true}
async function authJson(url,options={}){
  const response=await authFetch(url,options);
  const data=await response.json().catch(()=>({}));
  return {response,data,unauthorized:isUnauthorized(response)};
}

function showAuth(message=""){
  setAuthMode(inviteToken?"register":"login");
  authError.textContent=message;
  setAuthLocked(true);
  authUsername.focus();
}

function clearPendingMessage(){pendingBranch=null;pendingMessage=null;pendingRoot=false;pendingRootContent=""}

function clearAuth(){
  if(eventsAbortController)eventsAbortController.abort();
  stopStatusPolling();statusPanelOverride=null;serverStatusMessages=[];fileUploadAllowed=false;uploadFileChoice.disabled=true;renderServerStatusMessages();setStatusPanelVisible(false);serverStatusLight.className="http-server-status-light gray";setHeaderMenuOpen(false);
  eventsTask=null;authToken=null;currentUser=null;historyLoaded=false;activeStreamId=null;serverConnected=null;eventsReady=false;
  sendBtn.textContent="Send";sendBtn.classList.remove("cancel");sendBtn.disabled=true;
  localStorage.removeItem("commamatrix_auth_token");
  clearPendingAttachments();
  hideTyping();messagesEl.replaceChildren();itemsById=new Map();childrenByParent=new Map();selectedHeadId=null;newRootSelected=false;selectedLeafByNode=new Map();expandedNodes=new Set();deletedRootIds=new Set();showDeletedBranches=false;activeStreams={};streamingPreviews={};clearPendingMessage();
  passwordBtn.hidden=true;inviteBtn.hidden=true;logoutBtn.hidden=true;userLabel.textContent="";statusEl.textContent="Sign in required";statusEl.className="status";
  renderBranchPanel();
}

function applyUser(user){
  currentUser=user;loadDeletedBranches();showDeletedBranches=false;userLabel.textContent=user.username;passwordBtn.hidden=false;inviteBtn.hidden=!user.is_admin;logoutBtn.hidden=false;setUiStatus(eventsReady?"Ready":"Connecting...");setHeaderMenuOpen(false);setAuthLocked(false);
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

function latestBranchItemId(startId){
  const start=itemsById.get(startId);if(!start)return null;
  let latest=null;const stack=[start];const seen=new Set();
  while(stack.length){
    const item=stack.pop();if(seen.has(item.item_id))continue;seen.add(item.item_id);
    if(!childItems(item.item_id).length&&(!latest||Number(latest.item_id)<Number(item.item_id)))latest=item;
    stack.push(...childItems(item.item_id));
  }
  return latest?latest.item_id:null;
}

function latestGlobalItemId(){
  const items=[...itemsById.values()].filter(item=>{
    const rootId=rootIdForItem(item.item_id);
    return (rootId===null||!isRootDeleted(rootId))&&!childItems(item.item_id).length;
  });
  if(!items.length)return null;
  items.sort((a,b)=>Number(a.item_id)-Number(b.item_id));return items[items.length-1].item_id;
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
  selectedHeadId=preferred!==undefined&&chainContains(preferred,itemId)?preferred:(latestBranchItemId(itemId)||itemId);
  newRootSelected=false;
  clearPendingMessage();expandUserAncestors(itemId);rememberCurrentSelection();renderHistory();closeBranchPanel();
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
  const parentMissing=item.previous_item_id!==null&&item.previous_item_id!==undefined&&!itemsById.has(item.previous_item_id);
  itemsById.set(item.item_id,item);
  if(item.previous_item_id!==null&&item.previous_item_id!==undefined){const children=childrenByParent.get(item.previous_item_id)||[];children.push(item.item_id);children.sort((a,b)=>compareItems(itemsById.get(a),itemsById.get(b)));childrenByParent.set(item.previous_item_id,children)}
  if(parentMissing){
    await loadHistory(item.item_id);
    return;
  }
  let shouldSelect=selectedHeadId===null||item.previous_item_id===selectedHeadId;
  if(pendingItemMatches(item)){shouldSelect=true;newRootSelected=false;clearPendingMessage()}
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
  const content=document.createElement("div");content.className="message-content";
  if(item.item_type==="image_input"||item.item_type==="file_input"){
    const info=parseAttachmentContent(item.content);if(info){info.kind=item.item_type==="image_input"?"image":"file";content.appendChild(createAttachmentCard(info,{compact:true}))}else content.textContent=item.content;
  }else content.textContent=item.content;
  bubble.appendChild(content);wrapper.appendChild(bubble);
  const actions=document.createElement("div");actions.className="message-actions";
  const siblings=branchSiblings(item);const index=siblings.findIndex(sibling=>sibling.item_id===item.item_id);
  if(siblings.length>1){
    const nav=document.createElement("span");nav.className="branch-nav";
    const previous=document.createElement("button");previous.type="button";previous.textContent="←";previous.title="Previous branch";previous.setAttribute("aria-label","Previous branch");previous.disabled=index<=0;previous.addEventListener("click",()=>selectBranchNode(siblings[index-1].item_id));nav.appendChild(previous);
    const count=document.createElement("span");count.className="branch-count";count.textContent=(index+1)+" / "+siblings.length;nav.appendChild(count);
    const next=document.createElement("button");next.type="button";next.textContent="→";next.title="Next branch";next.setAttribute("aria-label","Next branch");next.disabled=index<0||index>=siblings.length-1;next.addEventListener("click",()=>selectBranchNode(siblings[index+1].item_id));nav.appendChild(next);actions.appendChild(nav);
  }
  if(item.item_type==="input"){
    const regenerate=document.createElement("button");regenerate.type="button";regenerate.textContent="↻";regenerate.title="Regenerate response";regenerate.setAttribute("aria-label","Regenerate response");regenerate.addEventListener("click",()=>regenerateBranch(item));actions.appendChild(regenerate);
    const edit=document.createElement("button");edit.type="button";edit.textContent="Edit";edit.title="Edit message";edit.addEventListener("click",()=>editMessage(item,wrapper,content,actions));actions.appendChild(edit);
  }
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

function stripOutputMarkers(content){
  return String(content||"").replace(/\[(image|file):[^\]\r\n]+\]/gi,"").replace(/[ \t]+([,.;:!?])/g,"$1").trim();
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
  const value=content===undefined||content===null?"":typeof content==="string"?content:JSON.stringify(content,null,2);
  if(!value.includes("\n")){const div=document.createElement("div");div.className="msg tool-result";const label=document.createElement("div");label.textContent="Tool Result";div.appendChild(label);div.appendChild(createPrettyBlock(value,null));messagesEl.appendChild(div);return}
  const details=document.createElement("details");details.className="msg tool-result";details.open=true;const summary=document.createElement("summary");summary.textContent="Tool Result";details.appendChild(summary);let lang=null;try{JSON.parse(value);lang="json"}catch{}details.appendChild(createPrettyBlock(value,lang));messagesEl.appendChild(details);
}

function addImageOutput(content){return addAttachmentMessage(content,"image")}
function addFileOutput(content){return addAttachmentMessage(content,"file")}

function addPlaceholder(type){const div=document.createElement("div");div.className="msg assistant";const placeholder=document.createElement("div");placeholder.className="placeholder";placeholder.textContent="["+type+"]";div.appendChild(placeholder);messagesEl.appendChild(div)}
function addError(text){addMessage("error",text,null)}

function showTyping(){
  if(typingIndicator)return;typingIndicator=document.createElement("div");typingIndicator.className="typing";typingIndicator.innerHTML="Thinking<span>.</span><span>.</span><span>.</span>";messagesEl.appendChild(typingIndicator);scrollToBottom();
}

function hideTyping(){if(typingIndicator){typingIndicator.remove();typingIndicator=null}}

function setProcessing(on,streamId=null){
  activeStreamId=on?streamId:null;sendBtn.textContent=on?"Cancel":"Send";sendBtn.classList.toggle("cancel",on);updateSendButton();setUiStatus(on?"Processing...":"Ready");if(!on)hideTyping();syncActionState();
}

function syncActionState(){
  const busy=Boolean(activeStreamId);for(const button of document.querySelectorAll(".message-actions button, #new-branch-btn, .branch-row button"))button.disabled=busy;
}

/** @param {DialogItem} item */
function renderItem(item){
  hideTyping();
  const preview=streamingPreviews[item.item_type];if(preview){preview.remove();delete streamingPreviews[item.item_type]}
  for(const key of Object.keys(activeStreams)){const stream=activeStreams[key];if(stream.item_type===item.item_type&&stream.previous_item_id===item.previous_item_id){stream.element.remove();delete activeStreams[key]}}
  if(item.meta?.is_tool_call_result&&!(["image_input","file_input"].includes(item.item_type))){addToolResult(item.content||"");return}
  switch(item.item_type){
    case "input":
    case "image_input":
    case "file_input":
      if(item.role==="user")messagesEl.appendChild(createUserEntry(item));else addPlaceholder(item.item_type);break;
    case "reasoning":addReasoning(item.content);break;
    case "tool_call":try{const toolCall=JSON.parse(item.content);addToolCall(toolCall.tool_name||"unknown",toolCall.tool_args||{})}catch{addToolCall("tool",item.content)}break;
    case "tool_call_result":if(lastWasCodeAct){try{const result=JSON.parse(item.content);finishCodeActSession(result.content)}catch{finishCodeActSession(item.content)}}else{try{const result=JSON.parse(item.content);addToolResult(result.content)}catch{addToolResult(item.content)}}break;
    case "output":addAssistantOutput(item);break;
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
  setUiStatus("Streaming...");
  if(!stream){let element;if(chunkType==="reasoning")element=addReasoning("");else if(chunkType==="tool_call"){element=document.createElement("details");element.className="msg tool-call";element.open=true;const summary=document.createElement("summary");summary.textContent="Tool: ...";element.appendChild(summary);const content=document.createElement("div");element.appendChild(content);messagesEl.appendChild(element)}else element=addMessage("assistant","","Assistant");stream={element,item_type:chunkType,previous_item_id:data.previous_item_id,text:""};activeStreams[streamId]=stream}
  stream.text+=(data.content||"");const contentEl=stream.element.querySelector("div:last-child")||stream.element;
  if(chunkType==="output"||chunkType==="reasoning")renderMarkdown(contentEl,stripOutputMarkers(stream.text));else contentEl.textContent=stream.text;
  scrollToBottom();
}

async function submitMessage(text,parentId,branch=null,attachments=[]){
  if(!authToken){showAuth();return false}
  if(!eventsReady){setUiStatus("Connecting...");return false}
  if(activeStreamId)return false;
  const previousItemId=parentId===null||parentId===undefined?null:parentId;
  pendingBranch=branch;pendingMessage={parentId:previousItemId,content:text,attachments};pendingRoot=!branch&&previousItemId===null;pendingRootContent=pendingRoot?text:"";setUiStatus("Sending...");sendBtn.disabled=true;
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/api/messages?stream=1"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:text,attachments:attachments.map(attachmentPayload),previous_item_id:previousItemId,timezone:browserTimezone()})});
    if(unauthorized){setProcessing(false);clearPendingMessage();return false}
    if(!response.ok){setProcessing(false);addError(data.error||data.detail||"Message was rejected");clearPendingMessage();return false}
    setProcessing(true,data.stream_id);showTyping();return true;
  }catch(error){addError("Network error: "+error.message);clearPendingMessage();setProcessing(false);return false}
}

async function send(){
  if(!eventsReady){setUiStatus("Connecting...");return}
  const text=inputEl.value.trim();if(activeStreamId)return;
  const uploading=pendingAttachments.some(attachment=>attachment.status==="uploading");if(uploading){setUiStatus("Wait for uploads to finish");return}
  const failed=pendingAttachments.some(attachment=>attachment.status!=="ready");if(failed){setUiStatus("Remove failed uploads");return}
  const attachments=pendingAttachments.filter(attachment=>attachment.status==="ready"&&(attachment.file_id||attachment.external&&attachment.url));
  if(!text&&!attachments.length)return;
  const fallbackParentId=latestGlobalItemId();
  const parentId=newRootSelected?null:(selectedHeadId??fallbackParentId);
  const sent=await submitMessage(text,parentId,null,attachments);if(sent){inputEl.value="";inputEl.style.height="auto";clearPendingAttachments()}else adjustInputHeight();
}

async function cancelProcessing(){
  const streamId=activeStreamId;if(!streamId)return;
  setProcessing(false);
  try{
    await authJson(serverUrl("/api/messages/")+streamId,{method:"DELETE"});
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
  clearPendingMessage();renderHistory();inputEl.focus();closeBranchPanel();
}

/** @param {StreamEvent} data */
async function handleServerEvent(data){
  if(data.type==="stream_chunk")handleStreamChunk(data);
  else if(data.type==="dialog_item")await applyDialogItem(data);
  else if(data.type==="typing"){
    if(data.active){showTyping();setUiStatus("Processing...")}else hideTyping();
  }
  else if(data.type==="message_done"){if(!activeStreamId||data.stream_id===activeStreamId)setProcessing(false)}
  else if(data.type==="error")addError(data.content||data.error||"Server error");
}

async function loadHistory(preferredHeadId=null){
  const knownItemIds=new Set(itemsById.keys());
  const {response,data,unauthorized}=await authJson(serverUrl("/api/history"));
  if(unauthorized)return
  if(!response.ok)throw new Error("History request failed");
  const previousSelected=selectedHeadId;rebuildGraph(data.items||[]);
  const preferredItem=typeof preferredHeadId==="number"?itemsById.get(preferredHeadId):null;
  const preferredContinuesSelection=Boolean(preferredItem&&((selectedHeadId!==null&&chainContains(preferredItem.item_id,selectedHeadId))||(selectedHeadId===null&&!newRootSelected)));
  const pendingItem=pendingMessage?[...itemsById.values()].filter(item=>!knownItemIds.has(item.item_id)&&pendingItemMatches(item)).sort(compareItems).pop():null;
  const keepSelection=historyLoaded&&!pendingMessage&&previousSelected!==null&&isVisibleItem(itemsById.get(previousSelected));
  if(pendingItem){selectedHeadId=latestBranchItemId(pendingItem.item_id)||pendingItem.item_id;clearPendingMessage()}else if(preferredContinuesSelection&&preferredItem)selectedHeadId=latestBranchItemId(preferredItem.item_id)||preferredItem.item_id;else if(keepSelection)selectedHeadId=previousSelected;else if(!historyLoaded&&!pendingMessage)selectedHeadId=latestGlobalItemId();else if(!pendingMessage&&selectedHeadId!==null&&!itemsById.has(selectedHeadId))selectedHeadId=latestGlobalItemId();
  historyLoaded=true;rememberCurrentSelection();renderHistory();
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
    setEventsReady(false);
    try{
      eventsAbortController=new AbortController();const response=await authFetch(serverUrl("/api/events"),{signal:eventsAbortController.signal});
      if(isUnauthorized(response))return
      if(!response.ok){setServerConnected(false);await new Promise(resolve=>setTimeout(resolve,1000));continue}
      setServerConnected(true);
      setEventsReady(true);
      try{await loadHistory()}catch(error){console.error("[CommaMatrix UI] event history refresh failed",error)}
      await handleEventStream(response);
      setEventsReady(false);setServerConnected(false);
    }catch(error){
      setEventsReady(false);
      if(!authToken||error.name==="AbortError")return;
      setServerConnected(false);await new Promise(resolve=>setTimeout(resolve,1000));
    }
    finally{eventsAbortController=null}
  }
}

function startEvents(){if(!eventsTask)eventsTask=eventsLoop().finally(()=>{eventsTask=null})}

async function loadCurrentUser(){
  if(!authToken){showAuth();return false}
  const {response,data,unauthorized}=await authJson(serverUrl("/api/me"));
  if(unauthorized||!response.ok){if(!unauthorized){clearAuth();showAuth()}return false}
  applyUser(data);
  startStatusPolling();
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
  if(!input)return
  button.addEventListener("click",()=>{const visible=input.type==="text";input.type=visible?"password":"text";button.textContent=visible?"Show":"Hide";button.setAttribute("aria-pressed",String(!visible))});
}

function closeAttachmentOverlay(){attachmentOverlay.classList.add("hidden")}
function openAttachmentOverlay(){if(!authToken){showAuth();return}uploadFileChoice.disabled=!fileUploadAllowed;closeLinkOverlay();attachmentOverlay.classList.remove("hidden")}
function closeLinkOverlay(){linkOverlay.classList.add("hidden");linkError.textContent=""}
function openLinkOverlay(){if(!authToken){showAuth();return}closeAttachmentOverlay();linkForm.reset();linkError.textContent="";linkOverlay.classList.remove("hidden");linkInput.focus()}
function chooseUpload(){closeAttachmentOverlay();if(!fileUploadAllowed){showUploadBlocked();return}fileInput.click()}

async function registerOrLogin(event){
  event.preventDefault();const username=authUsername.value.trim();const password=authPassword.value;authError.textContent="";
  if(!username||!password){authError.textContent="Username and password are required";return}
  if(authMode==="register"&&password!==authConfirm.value){authError.textContent="Passwords do not match";return}
  authSubmit.disabled=true;
  try{
    if(authMode==="register"){
      const response=await fetch(serverUrl("/api/register"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:inviteToken,username,password})});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=data.detail||"Registration failed";return}history.replaceState({},"",location.pathname);inviteToken=null;authMode="login";setAuthMode("login");authUsername.value=username;authPassword.value="";authError.textContent="Account created. Sign in with your new password.";return;
    }
    const response=await fetch(serverUrl("/api/login"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=data.detail||"Sign in failed";return}authToken=data.access_token;localStorage.setItem("commamatrix_auth_token",authToken);await loadCurrentUser();authForm.reset();
  }catch(error){console.error("[CommaMatrix UI] auth request failed",error);authError.textContent="Network error: "+error.message}finally{authSubmit.disabled=false}
}

document.querySelectorAll(".password-toggle").forEach(setupPasswordToggle);
headerMenuBtn.addEventListener("click",()=>setHeaderMenuOpen(!document.body.classList.contains("header-menu-open")));
serverStatusBtn.addEventListener("click",()=>{const visible=serverStatusPanel.classList.contains("visible");if(!visible&&!statusPanelOverride&&!serverStatusMessages.length)return;setStatusPanelVisible(!visible)});
passwordBtn.addEventListener("click",()=>{setHeaderMenuOpen(false);passwordError.textContent="";passwordForm.reset();passwordOverlay.classList.remove("hidden")});
document.getElementById("password-cancel").addEventListener("click",()=>passwordOverlay.classList.add("hidden"));
passwordForm.addEventListener("submit",async event=>{event.preventDefault();passwordError.textContent="";const next=document.getElementById("new-password").value;if(next!==document.getElementById("new-password-confirm").value){passwordError.textContent="Passwords do not match";return}try{const {response,data,unauthorized}=await authJson(serverUrl("/api/password"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({old_password:document.getElementById("old-password").value,new_password:next})});if(unauthorized)return;if(!response.ok){passwordError.textContent=data.detail||"Password change failed";return}passwordOverlay.classList.add("hidden")}catch(error){passwordError.textContent="Network error: "+error.message}});
inviteBtn.addEventListener("click",async()=>{setHeaderMenuOpen(false);const {response,data,unauthorized}=await authJson(serverUrl("/api/invite"),{method:"POST"});if(unauthorized)return;if(!response.ok){addError(data.detail||"Could not create invitation");return}inviteUrl.textContent=data.url;inviteOverlay.classList.remove("hidden")});
document.getElementById("invite-copy").addEventListener("click",async function(){await navigator.clipboard.writeText(inviteUrl.textContent);this.textContent="Copied";setTimeout(()=>{this.textContent="Copy link"},1200)});
document.getElementById("invite-close").addEventListener("click",()=>inviteOverlay.classList.add("hidden"));
attachmentCancel.addEventListener("click",closeAttachmentOverlay);
insertLinkChoice.addEventListener("click",openLinkOverlay);
uploadFileChoice.addEventListener("click",chooseUpload);
linkCancel.addEventListener("click",closeLinkOverlay);
linkForm.addEventListener("submit",event=>{event.preventDefault();const url=httpUrl(linkInput.value);if(!url){linkError.textContent="Enter a valid HTTP or HTTPS URL";return}addExternalLink(url);closeLinkOverlay()});
logoutBtn.addEventListener("click",logout);authForm.addEventListener("submit",event=>{void registerOrLogin(event)});sendBtn.addEventListener("click",()=>{if(activeStreamId)void cancelProcessing();else void send()});attachBtn.addEventListener("click",openAttachmentOverlay);fileInput.addEventListener("change",event=>{uploadFiles(event.target.files);fileInput.value=""});inputArea.addEventListener("drop",handleDrop);window.addEventListener("dragenter",handlePageDragEnter);window.addEventListener("dragover",handlePageDragOver);window.addEventListener("dragleave",handlePageDragLeave);window.addEventListener("drop",handlePageDrop);window.addEventListener("dragend",resetPageDrag);newBranchBtn.addEventListener("click",newBranch);activeBranchesBtn.addEventListener("click",()=>setBranchView(false));deletedBranchesBtn.addEventListener("click",()=>setBranchView(true));branchOpenBtn.addEventListener("click",openBranchPanel);branchCloseBtn.addEventListener("click",closeBranchPanel);branchBackdrop.addEventListener("click",closeBranchPanel);
inputEl.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();void send()}});inputEl.addEventListener("input",adjustInputHeight);window.addEventListener("resize",adjustInputHeight);

setAuthMode(authMode);renderBranchPanel();if(inviteToken){clearAuth();showAuth()}else void loadCurrentUser();
})();
