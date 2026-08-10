// builtin/http_connector/ui/app.js
/** @typedef {{origin_type?: string, platform?: string, http_user_id?: number}} DialogOrigin */
/** @typedef {{item_id: number|null, previous_item_id: number|null, item_type?: string, role?: string, content?: string, user?: string, origin?: DialogOrigin, created_at?: string|null, external_id?: string|null, branch_head_id?: number|null, branch_root_id?: number|null, branch_preview?: string, branch_updated_at?: string|null, meta?: Record<string, unknown>}} DialogItem */
/** @typedef {{tool_name?: string, tool_call_id?: string}} StreamMeta */
/** @typedef {{type?: string, item_id?: number|null, item_type?: string, role?: string, content?: string, error?: string, active?: boolean, previous_item_id?: number|null, stream_id?: string|null, meta?: StreamMeta}} StreamEvent */
/* global hljs, marked, DOMPurify */
(function(){
"use strict";

const SERVER_ROOT="/commamatrix";
function serverUrl(path){return SERVER_ROOT+path}
const LANGUAGE_STORAGE_KEY="commamatrix_ui_language";
const translations={
  en:{
    "common.cancel":"Cancel","common.close":"Close","common.save":"Save",
    "language.english":"English","language.russian":"Русский","language.switchTo":"Switch to {{language}}",
    "header.openBranches":"Open branches","header.closeBranches":"Close branches","header.serverStatus":"Server status","header.openAccountMenu":"Open account menu","header.closeAccountMenu":"Close account menu",
    "account.changePassword":"Change password","account.changeUsername":"Change name","account.addUser":"Add user","account.logOut":"Log out",
    "status.signInRequired":"Sign in required","status.ready":"Ready","status.connecting":"Connecting...","status.disconnected":"Disconnected","status.processing":"Processing...","status.streaming":"Streaming...","status.sending":"Sending...","status.waitUploads":"Wait for uploads to finish","status.removeFailedUploads":"Remove failed uploads",
    "branches.panelLabel":"Conversation branches","branches.title":"Branches","branches.description":"Choose a conversation","branches.new":"+ New branch","branches.filters":"Branch filters","branches.active":"Active","branches.deleted":"Deleted branches","branches.select":"Select branch","branches.collapse":"Collapse branch","branches.expand":"Expand branch","branches.restore":"Restore branch","branches.hide":"Hide branch","branches.noDeleted":"No deleted conversations.","branches.empty":"No conversations yet.","branches.emptyMessage":"[empty message]","branches.today":"today","branches.yesterday":"yesterday","branches.thisWeek":"this week","branches.thisMonth":"this month","branches.older":"older",
    "chat.messageLabel":"Message","chat.placeholder":"Type a message...","chat.send":"Send","chat.cancel":"Cancel",
    "attachments.dropHere":"Drop a link or file here","attachments.add":"Add a link or file","attachments.addToMessage":"Add to message","attachments.chooseHow":"Choose how to add content to your message.","attachments.insertLink":"Insert link","attachments.uploadFile":"Upload file","attachments.linkDescription":"The link will be added as an attachment and sent directly without saving contents.","attachments.url":"URL","attachments.uploadRequirement":"File uploads require a public http-server address",
    "auth.signIn":"Sign in","auth.createAccount":"Create account","auth.loginDescription":"Use your CommaMatrix account to connect to this agent.","auth.registerDescription":"Use the one-time invitation to create an account.","auth.username":"Username","auth.password":"Password","auth.confirmPassword":"Confirm password","auth.show":"Show","auth.hide":"Hide","auth.register":"Register",
    "password.title":"Change password","password.description":"Set a new password for the current account.","password.current":"Current password","password.new":"New password","password.confirmNew":"Confirm new password",
    "username.title":"Change name","username.description":"Use 2-32 Unicode characters. Letters from any language are allowed; spaces, digits, underscores, hyphens, dots and apostrophes can separate words.","username.label":"New name",
    "invite.title":"New user invitation","invite.description":"Give this one-time link to the person who should register.","invite.ready":"The invitation link is ready. Send it to the user.","invite.copy":"Copy link","invite.copied":"Copied",
    "attachment.image":"IMAGE","attachment.file":"FILE","attachment.link":"LINK","attachment.imageUnavailable":"Image unavailable","attachment.fileUnavailable":"File unavailable","attachment.uploading":"Uploading...","attachment.uploadFailed":"Upload failed","attachment.externalLink":"External link","attachment.ready":"Ready","attachment.remove":"Remove {{name}}",
    "message.assistant":"Assistant","message.reasoning":"Reasoning","message.codeAct":"CodeAct session","message.codeActElapsed":" ({{seconds}}s)","message.scrollToBottom":"Scroll to bottom","message.result":"Result","message.tool":"Tool: {{name}}","message.toolPlaceholder":"Tool: ...","message.toolResult":"Tool Result","message.thinking":"Thinking","message.streamingHelp":"If streaming gets stuck, reload the page (F5).","message.previousBranch":"Previous branch","message.nextBranch":"Next branch","message.regenerate":"Regenerate response","message.edit":"Edit","message.imageInput":"[image input]","message.fileInput":"[file input]","message.output":"[output]",
    "error.interface":"Interface error: {{message}}","error.unknown":"Unknown error","error.sessionExpired":"Your session has expired. Sign in again.","error.authenticationRequired":"Authentication required","error.fileRequestFailed":"File request failed","error.noPublicAddress":"You cannot upload files for LLM: CommaMatrix is not visible from the Internet.","error.uploadFailed":"Upload failed","error.messageRejected":"Message was rejected","error.network":"Network error: {{message}}","error.cancelRequest":"Cancel request failed: {{message}}","error.server":"Server error","error.couldNotLoadBranch":"Could not load branch: {{message}}","error.couldNotLoadHistory":"Could not load history: {{message}}","error.historyRequest":"History request failed","error.passwordMismatch":"Passwords do not match","error.credentialsRequired":"Username and password are required","error.usernameRequired":"Name is required","error.usernameLength":"Name must contain between 2 and 32 characters","error.usernameLetter":"Name must contain at least one letter","error.usernameEdges":"Name must start and end with a letter or number","error.usernameCharacters":"Name contains unsupported characters","error.usernameTaken":"That name is already taken","error.usernameChange":"Name change failed","error.registration":"Registration failed","error.signIn":"Sign in failed","error.accountCreated":"Account created. Sign in with your new password.","error.passwordChange":"Password change failed","error.invitation":"Could not create invitation","error.invalidUrl":"Enter a valid HTTP or HTTPS URL","error.eventsStream":"Events stream returned HTTP {{status}}","error.eventsFailed":"Events stream failed","error.eventsDisconnected":"Events stream disconnected","error.eventsAborted":"Events stream aborted","status.updateAvailable":"A new version is available: close CommaMatrix, download and run","status.updateInstaller":"installer"
  },
  ru:{
    "common.cancel":"Отмена","common.close":"Закрыть","common.save":"Сохранить",
    "language.english":"English","language.russian":"Русский","language.switchTo":"Переключить на язык: {{language}}",
    "header.openBranches":"Открыть ветки","header.closeBranches":"Закрыть ветки","header.serverStatus":"Состояние сервера","header.openAccountMenu":"Открыть меню аккаунта","header.closeAccountMenu":"Закрыть меню аккаунта",
    "account.changePassword":"Сменить пароль","account.changeUsername":"Сменить имя","account.addUser":"Добавить пользователя","account.logOut":"Выйти",
    "status.signInRequired":"Нужно войти","status.ready":"Готов","status.connecting":"Подключение...","status.disconnected":"Нет соединения","status.processing":"Обработка...","status.streaming":"Отвечаю...","status.sending":"Отправка...","status.waitUploads":"Дождитесь завершения загрузки","status.removeFailedUploads":"Удалить неудачные загрузки",
    "branches.panelLabel":"Диалоги","branches.title":"Диалоги","branches.description":"Выберите диалог","branches.new":"+ Новый диалог","branches.filters":"Фильтры диалогов","branches.active":"Активные","branches.deleted":"Удалённые диалоги","branches.select":"Выбрать диалог","branches.collapse":"Свернуть диалог","branches.expand":"Развернуть диалог","branches.restore":"Восстановить диалог","branches.hide":"Скрыть диалог","branches.noDeleted":"Удалённых диалогов нет.","branches.empty":"Диалогов пока нет.","branches.emptyMessage":"[пустое сообщение]","branches.today":"сегодня","branches.yesterday":"вчера","branches.thisWeek":"на этой неделе","branches.thisMonth":"в этом месяце","branches.older":"раньше",
    "chat.messageLabel":"Сообщение","chat.placeholder":"Введите сообщение...","chat.send":"Отправить","chat.cancel":"Отменить",
    "attachments.dropHere":"Перетащите сюда ссылку или файл","attachments.add":"Добавить ссылку или файл","attachments.addToMessage":"Добавить к сообщению","attachments.chooseHow":"Выберите, как добавить содержимое к сообщению.","attachments.insertLink":"Вставить ссылку","attachments.uploadFile":"Загрузить файл","attachments.linkDescription":"Ссылка будет добавлена как вложение и отправлена напрямую без сохранения содержимого.","attachments.url":"URL","attachments.uploadRequirement":"Для загрузки файлов HTTP-сервер должен быть доступен из интернета",
    "auth.signIn":"Войти","auth.createAccount":"Создать аккаунт","auth.loginDescription":"Используйте аккаунт CommaMatrix для подключения к этому агенту.","auth.registerDescription":"Используйте одноразовое приглашение для создания аккаунта.","auth.username":"Имя пользователя","auth.password":"Пароль","auth.confirmPassword":"Подтвердите пароль","auth.show":"Показать","auth.hide":"Скрыть","auth.register":"Зарегистрироваться",
    "password.title":"Сменить пароль","password.description":"Задайте новый пароль для текущего аккаунта.","password.current":"Текущий пароль","password.new":"Новый пароль","password.confirmNew":"Подтвердите новый пароль",
    "username.title":"Сменить имя","username.description":"Используйте от 2 до 32 символов Unicode. Разрешены буквы любых языков; пробелы, цифры, подчёркивания, дефисы, точки и апострофы могут разделять слова.","username.label":"Новое имя",
    "invite.title":"Приглашение нового пользователя","invite.description":"Передайте эту одноразовую ссылку пользователю, который должен зарегистрироваться.","invite.ready":"Ссылка-приглашение готова. Отправьте её пользователю.","invite.copy":"Копировать ссылку","invite.copied":"Скопировано",
    "attachment.image":"КАРТИНКА","attachment.file":"ФАЙЛ","attachment.link":"ССЫЛКА","attachment.imageUnavailable":"Картинка недоступна","attachment.fileUnavailable":"Файл недоступен","attachment.uploading":"Загрузка...","attachment.uploadFailed":"Не удалось загрузить","attachment.externalLink":"Внешняя ссылка","attachment.ready":"Готово","attachment.remove":"Удалить {{name}}",
    "message.assistant":"Ассистент","message.reasoning":"Рассуждение","message.codeAct":"Сессия CodeAct","message.codeActElapsed":" ({{seconds}} с)","message.scrollToBottom":"Прокрутить вниз","message.result":"Результат","message.tool":"Инструмент: {{name}}","message.toolPlaceholder":"Инструмент: ...","message.toolResult":"Результат инструмента","message.thinking":"Обработка","message.streamingHelp":"Если поток завис, перезагрузите страницу (F5).","message.previousBranch":"Предыдущая ветка","message.nextBranch":"Следующая ветка","message.regenerate":"Сгенерировать ответ заново","message.edit":"Изменить","message.imageInput":"[изображение]","message.fileInput":"[файл]","message.output":"[результат]",
    "error.interface":"Ошибка интерфейса: {{message}}","error.unknown":"Неизвестная ошибка","error.sessionExpired":"Срок действия сессии истёк. Войдите снова.","error.authenticationRequired":"Требуется аутентификация","error.fileRequestFailed":"Не удалось получить файл","error.noPublicAddress":"Невозможно загрузить файлы для LLM: CommaMatrix недоступен из интернета.","error.uploadFailed":"Не удалось загрузить файл","error.messageRejected":"Сообщение отклонено","error.network":"Ошибка сети: {{message}}","error.cancelRequest":"Не удалось отменить запрос: {{message}}","error.server":"Ошибка сервера","error.couldNotLoadBranch":"Не удалось загрузить ветку: {{message}}","error.couldNotLoadHistory":"Не удалось загрузить историю: {{message}}","error.historyRequest":"Не удалось запросить историю","error.passwordMismatch":"Пароли не совпадают","error.credentialsRequired":"Введите имя пользователя и пароль","error.usernameRequired":"Введите имя","error.usernameLength":"Имя должно содержать от 2 до 32 символов","error.usernameLetter":"Имя должно содержать хотя бы одну букву","error.usernameEdges":"Имя должно начинаться и заканчиваться буквой или цифрой","error.usernameCharacters":"Имя содержит недопустимые символы","error.usernameTaken":"Это имя уже занято","error.usernameChange":"Не удалось сменить имя","error.registration":"Не удалось зарегистрироваться","error.signIn":"Не удалось войти","error.accountCreated":"Аккаунт создан. Войдите с новым паролем.","error.passwordChange":"Не удалось сменить пароль","error.invitation":"Не удалось создать приглашение","error.invalidUrl":"Введите корректный HTTP- или HTTPS-адрес","error.eventsStream":"Поток событий вернул HTTP {{status}}","error.eventsFailed":"Поток событий завершился с ошибкой","error.eventsDisconnected":"Поток событий отключён","error.eventsAborted":"Поток событий прерван","status.updateAvailable":"Доступна новая версия: закройте CommaMatrix, скачайте и запустите","status.updateInstaller":"установщик"
  }
};
const serverErrorTranslations={"public_address_required":"error.noPublicAddress","update_available":"status.updateAvailable"};
let locale=(()=>{try{const stored=localStorage.getItem(LANGUAGE_STORAGE_KEY);if(stored&&translations[stored])return stored}catch{}return navigator.language?.toLowerCase().startsWith("ru")?"ru":"en"})();
function translationAttributeKey(attribute){return "i18n"+attribute.split("-").map(part=>part[0].toUpperCase()+part.slice(1)).join("")}
function t(key,values={}){const template=translations[locale][key]??translations.en[key]??String(key??"");return String(template).replace(/\{\{(\w+)\}\}/g,(_,name)=>String(values[name]??""))}
function localizedServerMessage(item){const code=typeof item?.code==="string"?item.code.trim():"";const text=[item?.text,item?.message,item?.error,item?.detail,item?.content].find(value=>typeof value==="string"&&value.trim())?.trim()||"";if(code){const key=serverErrorTranslations[code]||(code.startsWith("error.")?code:"error."+code);if(translations[locale]?.[key]||translations.en?.[key])return t(key)}return text||code}
function setI18nText(element,key,values={}){element.dataset.i18n=key;if(Object.keys(values).length)element.dataset.i18nValues=JSON.stringify(values);else delete element.dataset.i18nValues;element.textContent=t(key,values)}
function setI18nAttribute(element,attribute,key,values={}){element.dataset[translationAttributeKey(attribute)]=key;if(Object.keys(values).length)element.dataset.i18nValues=JSON.stringify(values);element.setAttribute(attribute,t(key,values))}
function applyTranslations(){
  for(const element of document.querySelectorAll("[data-i18n]")){let values={};try{values=JSON.parse(element.dataset.i18nValues||"{}")}catch{}element.textContent=t(element.dataset.i18n,values)}
  for(const attribute of ["title","aria-label","placeholder"]){for(const element of document.querySelectorAll(`[data-i18n-${attribute}]`)){let values={};try{values=JSON.parse(element.dataset.i18nValues||"{}")}catch{}element.setAttribute(attribute,t(element.dataset[translationAttributeKey(attribute)],values))}}
  for(const button of document.querySelectorAll(".password-toggle"))setI18nText(button,button.dataset.visible==="true"?"auth.hide":"auth.show");
  const targets=[
    ["#branch-open","aria-label","header.openBranches"],["#branch-open","title","header.openBranches"],["#branch-close","aria-label","header.closeBranches"],["#branch-close","title","header.closeBranches"],["#http-server-status-btn","aria-label","header.serverStatus"],["#http-server-status-btn","title","header.serverStatus"],["#header-menu-btn","aria-label","header.openAccountMenu"],["#header-menu-btn","title","header.openAccountMenu"],["#branch-panel","aria-label","branches.panelLabel"],[".branch-panel-header h2","text","branches.title"],[".branch-panel-header p","text","branches.description"],["#new-branch-btn","text","branches.new"],[".branch-tabs","aria-label","branches.filters"],["#active-branches-btn","text","branches.active"],["#deleted-branches-btn","aria-label","branches.deleted"],["#deleted-branches-btn","title","branches.deleted"],["#username-btn","text","account.changeUsername"],["#password-btn","text","account.changePassword"],["#invite-btn","text","account.addUser"],["#logout-btn","text","account.logOut"],["#status","text","status.signInRequired"],["label[for=input]","text","chat.messageLabel"],["#attach-btn","title","attachments.add"],["#attach-btn","aria-label","attachments.add"],["#drop-overlay","text","attachments.dropHere"],["#input","placeholder","chat.placeholder"],["#attachment-overlay h2","text","attachments.addToMessage"],["#attachment-overlay p","text","attachments.chooseHow"],["#insert-link-choice","text","attachments.insertLink"],["#upload-file-choice","text","attachments.uploadFile"],["#attachment-cancel","text","common.cancel"],["#link-overlay h2","text","attachments.insertLink"],["#link-overlay p","text","attachments.linkDescription"],["#link-overlay label","text","attachments.url"],["#link-form button[type=submit]","text","attachments.insertLink"],["#link-cancel","text","common.cancel"],["#auth-title","text","auth.signIn"],["#auth-description","text","auth.loginDescription"],["label[for=auth-username]","text","auth.username"],["label[for=auth-password]","text","auth.password"],["#auth-confirm-label","text","auth.confirmPassword"],["#auth-submit","text","auth.signIn"],["#password-overlay h2","text","password.title"],["#password-overlay p","text","password.description"],["label[for=old-password]","text","password.current"],["label[for=new-password]","text","password.new"],["label[for=new-password-confirm]","text","password.confirmNew"],["#password-overlay form>button[type=submit]","text","password.title"],["#password-cancel","text","common.cancel"],["#username-overlay h2","text","username.title"],["#username-overlay p","text","username.description"],["label[for=username-input]","text","username.label"],["#username-form button[type=submit]","text","username.title"],["#username-cancel","text","common.cancel"],["#invite-overlay h2","text","invite.title"],["#invite-overlay p:first-of-type","text","invite.description"],["#invite-overlay p:nth-of-type(2)","text","invite.ready"],["#invite-copy","text","invite.copy"],["#invite-close","text","common.close"]
  ];
  for(const [selector,attribute,key] of targets){const element=document.querySelector(selector);if(!element)continue;if(attribute==="text")setI18nText(element,key);else setI18nAttribute(element,attribute,key)}
  if(typeof sendBtn!=="undefined")setI18nText(sendBtn,activeStreamId?"chat.cancel":"chat.send");
  document.documentElement.lang=locale;
}
function updateLanguageButton(){const target=locale==="ru"?"english":"russian";languageBtn.textContent=t("language."+target);const label=t("language.switchTo",{language:t("language."+target)});languageBtn.title=label;languageBtn.setAttribute("aria-label",label)}
function setLocale(nextLocale){if(!translations[nextLocale]||nextLocale===locale)return;locale=nextLocale;try{localStorage.setItem(LANGUAGE_STORAGE_KEY,locale)}catch{}applyTranslations();updateLanguageButton();setAuthMode(authMode);renderAttachmentPreviews();renderServerStatusMessages();renderBranchPanel();updateCodeActElapsed();if(currentStatusKey)setUiStatus(currentStatusKey)}
window.__commamatrixUiLoaded=true;
window.addEventListener("error",event=>{console.error("[CommaMatrix UI] uncaught error",event.error||event.message);const error=document.getElementById("auth-error");if(error)error.textContent=t("error.interface",{message:event.message})});
window.addEventListener("unhandledrejection",event=>{console.error("[CommaMatrix UI] unhandled rejection",event.reason);const error=document.getElementById("auth-error");if(error)error.textContent=t("error.interface",{message:event.reason?.message||event.reason||t("error.unknown")})});

const messagesEl=document.getElementById("messages");
const chatColumn=document.getElementById("chat-column");
const scrollBottomBtn=document.getElementById("scroll-bottom-btn");
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
const usernameBtn=document.getElementById("username-btn");
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
const usernameOverlay=document.getElementById("username-overlay");
const usernameForm=document.getElementById("username-form");
const usernameInput=document.getElementById("username-input");
const usernameError=document.getElementById("username-error");
const inviteOverlay=document.getElementById("invite-overlay");
const attachmentOverlay=document.getElementById("attachment-overlay");
const insertLinkChoice=document.getElementById("insert-link-choice");
const uploadFileChoice=document.getElementById("upload-file-choice");
const attachmentCancel=document.getElementById("attachment-cancel");
const linkOverlay=document.getElementById("link-overlay");
const linkForm=document.getElementById("link-form");
const linkInput=document.getElementById("link-input");
const linkError=document.getElementById("link-error");
const linkCancel=document.getElementById("link-cancel");
let languageBtn=document.getElementById("language-btn");if(!languageBtn){languageBtn=document.createElement("button");languageBtn.id="language-btn";languageBtn.type="button";languageBtn.setAttribute("aria-live","polite");logoutBtn.parentElement.insertBefore(languageBtn,logoutBtn)}

let inviteToken=new URLSearchParams(location.search).get("token");
let inviteLink="";
let authToken=localStorage.getItem("commamatrix_auth_token");
let currentUser=null;
let authMode=inviteToken?"register":"login";
let activeStreamId=null;
let eventsTask=null;
let eventsAbortController=null;
let eventsRequest=null;
let eventsReady=false;
let typingIndicator=null;
let codeactSpinnerEl=null;
let codeactActiveEl=null;
let codeactStreamArgs="";
let codeactStreamToolId=null;
let lastWasCodeAct=false;
let codeactStartedAt=null;
let codeactElapsedSeconds=0;
let codeactTimer=null;
let activeStreams={};
let streamingPreviews={};
let messagesPinnedToBottom=true;
let scrollFrame=null;
let smoothScrollInProgress=false;
let userScrollPending=false;
const SCROLL_BOTTOM_THRESHOLD=24;
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
/** @type {DialogItem[]} */
let historyHeads=[];
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
let currentStatusKey="signInRequired";
const STATUS_POLL_INTERVAL_MS=3000;

function updateSendButton(){
  sendBtn.disabled=!currentUser||document.body.classList.contains("auth-locked")||(!activeStreamId&&!eventsReady);
}

function setEventsReady(ready){
  eventsReady=ready;updateSendButton();
  if(authToken&&!activeStreamId)setUiStatus(ready||serverConnected===true?"ready":"connecting");
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
  setI18nAttribute(headerMenuBtn,"aria-label",open?"header.closeAccountMenu":"header.openAccountMenu");
  setI18nAttribute(headerMenuBtn,"title",open?"header.closeAccountMenu":"header.openAccountMenu");
}

function setStatusPanelVisible(visible){
  serverStatusPanel.classList.toggle("visible",visible);
  serverStatusBtn.setAttribute("aria-expanded",String(visible));
}

function renderServerStatusMessages(){
  const messages=statusPanelOverride?[statusPanelOverride]:serverStatusMessages;
  serverStatusPanel.replaceChildren();
  for(const item of messages){
    const text=localizedServerMessage(item);if(!text)continue;const message=document.createElement("div");message.className="http-server-status-message "+item.severity;message.textContent=text;const rawUrl=typeof item.link_url==="string"?item.link_url.trim():"";const linkText=item.code==="update_available"?t("status.updateInstaller"):typeof item.link_text==="string"?item.link_text.trim():"";if(rawUrl&&linkText){try{const url=new URL(rawUrl,window.location.href);if(["http:","https:"].includes(url.protocol)){const link=document.createElement("a");link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";link.textContent=linkText;message.append(document.createTextNode(" "),link)}}catch{}}serverStatusPanel.appendChild(message);
  }
}

function setUiStatus(key){
  currentStatusKey=key;
  const effectiveKey=serverConnected===false?"disconnected":key;
  const kind=["disconnected","connecting","processing","streaming","sending","ready"].includes(effectiveKey)?effectiveKey:"";
  setI18nText(statusEl,"status."+effectiveKey);statusEl.className="status"+(kind?" status-"+kind:"");
  statusEl.title=effectiveKey==="streaming"?t("message.streamingHelp"):"";
}
function serverStatusSeverity(){return serverStatusMessages.some(item=>item.severity==="red")?"red":serverStatusMessages.length?"yellow":"green"}
function updateServerStatusLight(){const severity=serverConnected===false?"gray":statusPanelOverride?.severity||serverStatusSeverity();serverStatusLight.className="http-server-status-light "+severity}
function setServerConnected(connected){
  const wasDisconnected=serverConnected===false;const wasConnecting=!activeStreamId&&currentStatusKey==="connecting";serverConnected=connected;updateServerStatusLight();updateSendButton();
  if(!connected)setUiStatus("disconnected");else if(wasDisconnected||wasConnecting)setUiStatus("ready");
}

function updateServerStatus(data){
  serverStatusMessages=Array.isArray(data.messages)?data.messages.filter(item=>item&&["yellow","red"].includes(item.severity)&&localizedServerMessage(item)).map(item=>({code:typeof item.code==="string"?item.code:undefined,text:typeof item.text==="string"?item.text:typeof item.message==="string"?item.message:undefined,severity:item.severity,link_url:typeof item.link_url==="string"?item.link_url:undefined,link_text:typeof item.link_text==="string"?item.link_text:undefined})):[];
  fileUploadAllowed=data.file_upload_allowed===true;
  uploadFileChoice.disabled=!fileUploadAllowed;
  setI18nAttribute(uploadFileChoice,"title",fileUploadAllowed?"attachments.uploadFile":"attachments.uploadRequirement");
  setServerConnected(true);
  renderServerStatusMessages();
}

function showTemporaryStatus(message,severity="yellow"){
  statusPanelOverride={...(typeof message==="string"?{text:message}:message),severity};
  updateServerStatusLight();
  renderServerStatusMessages();setStatusPanelVisible(true);
  if(statusOverrideTimer)clearTimeout(statusOverrideTimer);
  statusOverrideTimer=setTimeout(()=>{statusPanelOverride=null;statusOverrideTimer=null;updateServerStatusLight();renderServerStatusMessages();setStatusPanelVisible(false)},5000);
}

function showUploadBlocked(){showTemporaryStatus({code:"public_address_required"});}

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
  setI18nText(authTitle,register?"auth.createAccount":"auth.signIn");
  setI18nText(authDescription,register?"auth.registerDescription":"auth.loginDescription");
  authConfirmLabel.hidden=!register;
  authConfirm.hidden=!register;
  authConfirm.required=register;
  authPassword.autocomplete=register?"new-password":"current-password";
  setI18nText(authSubmit,register?"auth.register":"auth.signIn");
  authError.textContent="";
}

const USERNAME_ALLOWED_RE=/^[\p{L}\p{M}\p{N} ._'-]+$/u;
const USERNAME_EDGE_RE=/^[\p{L}\p{N}]$/u;
function validateUsername(value){
  const normalized=String(value??"").normalize("NFC").trim().split(/\s+/).filter(Boolean).join(" ");
  const chars=[...normalized];
  if(!normalized)return {value:normalized,errorKey:"error.usernameRequired"};
  if(chars.length<2||chars.length>32)return {value:normalized,errorKey:"error.usernameLength"};
  if(!chars.some(char=>/\p{L}/u.test(char)))return {value:normalized,errorKey:"error.usernameLetter"};
  if(!USERNAME_EDGE_RE.test(chars[0])||!USERNAME_EDGE_RE.test(chars[chars.length-1]))return {value:normalized,errorKey:"error.usernameEdges"};
  if(!USERNAME_ALLOWED_RE.test(normalized))return {value:normalized,errorKey:"error.usernameCharacters"};
  return {value:normalized,errorKey:null};
}
function localizedAuthError(data,fallback){
  const detail=data?.detail||data?.error;
  const errorKeys={
    "Username is required":"error.usernameRequired",
    "Username must be between 2 and 32 characters":"error.usernameLength",
    "Username must contain at least one letter":"error.usernameLetter",
    "Username must start and end with a letter or number":"error.usernameEdges",
    "Username contains unsupported characters":"error.usernameCharacters",
    "Username already taken for this app":"error.usernameTaken"
  };
  return detail?(errorKeys[detail]?t(errorKeys[detail]):detail):t(fallback);
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
  if(isUnauthorized(response))throw new Error(t("error.authenticationRequired"))
  if(!response.ok)throw new Error(t("error.fileRequestFailed"))
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
    const image=document.createElement("img");image.alt=info.name||t("attachment.image");card.appendChild(image);
    setResource(image,resource,"src",()=>{image.alt=t("attachment.imageUnavailable")})
  }else{
    const icon=document.createElement("span");icon.className="attachment-icon";setI18nText(icon,info.kind==="image"?"attachment.image":"attachment.file");card.appendChild(icon);
  }
  const details=document.createElement("span");details.className="attachment-info";
  if(info.kind!=="image"&&!info.error){
    const link=document.createElement("a");link.className="attachment-name";link.textContent=info.name||t("attachment.file");link.download=info.name||"file";link.rel="noopener noreferrer";
    setResource(link,resource,"href",()=>{link.textContent=(info.name||t("attachment.file"))+" (unavailable)"})
    details.appendChild(link);
  }else{const name=document.createElement("span");name.className="attachment-name";name.textContent=info.name||(info.kind==="image"?t("attachment.image"):t("attachment.file"));details.appendChild(name)}
  if(info.size!==undefined&&info.size!==null){const size=document.createElement("span");size.className="attachment-size";size.textContent=formatFileSize(info.size);details.appendChild(size)}
  if(info.error){const error=document.createElement("span");error.className="attachment-error";error.textContent=info.error;details.appendChild(error)}
  card.appendChild(details);return card;
}

function addAttachmentMessage(content,kind){
  const div=document.createElement("div");div.className="msg "+(kind==="image"?"image":"file");const info=parseAttachmentContent(content);
  if(info&&(info.ref||info.url||kind==="file")){info.kind=kind||info.kind;div.appendChild(createAttachmentCard(info))}else div.textContent=(kind==="image"?t("attachment.image"):t("attachment.file"))+": "+content;
  messagesEl.appendChild(div);scrollToBottom();return div;
}

function outputAttachments(item){
  const attachments=item?.meta?.http?.attachments;
  return Array.isArray(attachments)?attachments.filter(attachment=>attachment&&typeof attachment==="object"):[];
}

function addAssistantOutput(item){
  const wrapper=document.createElement("div");wrapper.className="message-entry assistant-entry";wrapper.dataset.itemId=String(item.item_id??"");
  const bubble=document.createElement("div");bubble.className="msg assistant";
  const role=document.createElement("div");role.className="role";setI18nText(role,"message.assistant");bubble.appendChild(role);
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
    if(attachment.kind==="image"&&attachment.previewUrl){const image=document.createElement("img");image.src=attachment.previewUrl;image.alt=attachment.name;preview.appendChild(image)}else{const icon=document.createElement("span");icon.className="attachment-icon";setI18nText(icon,attachment.external?"attachment.link":"attachment.file");preview.appendChild(icon)}
    const details=document.createElement("span");details.className="attachment-info";const name=document.createElement("span");name.className="attachment-name";name.textContent=attachment.name;details.appendChild(name);const status=document.createElement("span");status.className="attachment-status";if(attachment.status==="uploading")setI18nText(status,"attachment.uploading");else if(attachment.status==="failed")status.textContent=attachment.error||t("attachment.uploadFailed");else if(attachment.external)setI18nText(status,"attachment.externalLink");else if(formatFileSize(attachment.size))status.textContent=formatFileSize(attachment.size);else setI18nText(status,"attachment.ready");details.appendChild(status);preview.appendChild(details);
    const remove=document.createElement("button");remove.type="button";remove.className="attachment-remove";remove.textContent="×";setI18nAttribute(remove,"title","attachment.remove",{name:attachment.name});setI18nAttribute(remove,"aria-label","attachment.remove",{name:attachment.name});remove.addEventListener("click",()=>removePendingAttachment(attachment));preview.appendChild(remove);attachmentPreviewsEl.appendChild(preview);
  }
  updateScrollBottomPosition();
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

function addExternalLink(url){pendingAttachments.push(externalLinkAttachment(url));renderAttachmentPreviews();setUiStatus("ready")}

async function uploadFile(file){
  if(!authToken){showAuth();return false}
  if(!fileUploadAllowed){showUploadBlocked();return false}
  const attachment={name:file.name||"file",size:file.size,mime_type:file.type||"application/octet-stream",kind:(file.type||"").startsWith("image/")?"image":"file",status:"uploading",previewUrl:URL.createObjectURL(file)};pendingAttachments.push(attachment);renderAttachmentPreviews();
  const form=new FormData();form.append("file",file,attachment.name);form.append("purpose","user_data");
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/v1/files"),{method:"POST",body:form});
    if(unauthorized)return false
    if(!response.ok){attachment.status="failed";attachment.error=localizedServerMessage(data)||t("attachment.uploadFailed");renderAttachmentPreviews();return false}
    attachment.file_id=data.id||data.file_id;attachment.name=data.filename||data.name||attachment.name;attachment.mime_type=data.mime_type||attachment.mime_type;attachment.size=data.bytes??data.size_bytes??attachment.size;attachment.kind=attachment.mime_type.startsWith("image/")?"image":attachment.kind;attachment.url=data.content_url||data.url||fileContentUrl(attachment.file_id);attachment.ext=attachment.name.includes(".")?attachment.name.split(".").pop().toLowerCase():"";attachment.status="ready";
  }catch(error){attachment.status="failed";attachment.error=error.message||t("attachment.uploadFailed")}
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

function expireSession(){clearAuth();showAuth(t("error.sessionExpired"))}
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
  if(eventsRequest)eventsRequest.abort();
  stopStatusPolling();statusPanelOverride=null;serverStatusMessages=[];fileUploadAllowed=false;uploadFileChoice.disabled=true;renderServerStatusMessages();setStatusPanelVisible(false);serverStatusLight.className="http-server-status-light gray";setHeaderMenuOpen(false);
  eventsTask=null;authToken=null;currentUser=null;historyLoaded=false;activeStreamId=null;serverConnected=null;eventsReady=false;
  setI18nText(sendBtn,"chat.send");sendBtn.classList.remove("cancel");sendBtn.disabled=true;
  localStorage.removeItem("commamatrix_auth_token");
  clearPendingAttachments();
  hideTyping();hideCodeActSpinner();messagesEl.replaceChildren();messagesPinnedToBottom=true;updateScrollBottomButton();itemsById=new Map();childrenByParent=new Map();selectedHeadId=null;newRootSelected=false;selectedLeafByNode=new Map();expandedNodes=new Set();deletedRootIds=new Set();showDeletedBranches=false;historyHeads=[];activeStreams={};streamingPreviews={};clearPendingMessage();
  usernameBtn.hidden=true;passwordBtn.hidden=true;inviteBtn.hidden=true;logoutBtn.hidden=true;userLabel.textContent="";setUiStatus("signInRequired");
  renderBranchPanel();
}

function applyUser(user){
  currentUser=user;loadDeletedBranches();showDeletedBranches=false;userLabel.textContent=user.username;usernameBtn.hidden=false;passwordBtn.hidden=false;inviteBtn.hidden=!user.is_admin;logoutBtn.hidden=false;setUiStatus(eventsReady?"ready":"connecting");setHeaderMenuOpen(false);setAuthLocked(false);
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
  return historyHeads.filter(isVisibleItem);
}

function branchKey(item){
  return Number(item.branch_root_id??item.item_id);
}

function rememberCurrentSelection(){
  if(selectedHeadId===null||selectedHeadId===undefined)return;
  for(const item of currentChain())if(isUserItem(item))selectedLeafByNode.set(item.item_id,selectedHeadId);
}

function selectedVisibleId(){
  const visible=currentChain().filter(isVisibleItem);return visible.length?visible[visible.length-1].item_id:null;
}

async function selectBranchNode(itemId,branchHeadId=null){
  const item=itemsById.get(itemId)||historyHeads.find(head=>head.item_id===itemId);if(!item)return;
  const preferred=selectedLeafByNode.get(itemId);
  selectedHeadId=branchHeadId??(preferred!==undefined&&chainContains(preferred,itemId)?preferred:(latestBranchItemId(itemId)||itemId));
  newRootSelected=false;
  clearPendingMessage();renderBranchPanel();
  try{await loadHistory(selectedHeadId)}catch(error){addError(t("error.couldNotLoadBranch",{message:error.message}))}
  closeBranchPanel();
}

function groupForDate(timestamp){
  const date=new Date(timestamp);if(Number.isNaN(date.valueOf()))return "older";
  const now=new Date();
  const dayStart=value=>{const result=new Date(value);result.setHours(0,0,0,0);return result};
  const dateStart=dayStart(date);const today=dayStart(now);const days=Math.floor((today-dateStart)/86400000);
  if(days===0)return "today";
  if(days===1)return "yesterday";
  const weekStart=new Date(today);const day=(weekStart.getDay()+6)%7;weekStart.setDate(weekStart.getDate()-day);
  if(dateStart>=weekStart)return "thisWeek";
  if(date.getFullYear()===now.getFullYear()&&date.getMonth()===now.getMonth())return "thisMonth";
  return "older";
}

/** @param {DialogItem} root @returns {DialogItem} */
function rootLatestLeaf(root){
  const latest=itemsById.get(latestVisibleItemId(root.item_id))||itemsById.get(root.branch_head_id);
  if(latest)return latest;
  if(root.branch_updated_at)return {...root,item_id:root.branch_head_id??root.item_id,created_at:root.branch_updated_at};
  return root;
}

/** @param {DialogItem} root */
function branchPreview(root){
   if(root.branch_preview)return root.branch_preview;
  const descendants=[];const queue=[...childItems(root.item_id)];const seen=new Set();
  while(queue.length){
    const item=queue.shift();if(seen.has(item.item_id))continue;seen.add(item.item_id);descendants.push(item);queue.push(...childItems(item.item_id));
  }
  descendants.sort(compareItems);
  const preview=descendants.find(item=>{
    const userInput=item.role==="user"&&["input","image_input","file_input"].includes(item.item_type);
    const assistantOutput=item.role==="assistant"&&["output","image_output","file_output"].includes(item.item_type);
    return userInput||assistantOutput;
  })||{content:root.branch_preview||root.content};
  return preview.content||t("branches.emptyMessage");
}

function updateBranchTabs(){
  activeBranchesBtn.classList.toggle("active",!showDeletedBranches);activeBranchesBtn.setAttribute("aria-selected",String(!showDeletedBranches));
  deletedBranchesBtn.classList.toggle("active",showDeletedBranches);deletedBranchesBtn.setAttribute("aria-selected",String(showDeletedBranches));
}

function selectReplacementRoot(excludedRootId){
  const roots=visibleRoots().filter(root=>branchKey(root)!==excludedRootId&&!isRootDeleted(branchKey(root)));
  roots.sort((a,b)=>itemTime(rootLatestLeaf(b))-itemTime(rootLatestLeaf(a))||Number(b.item_id)-Number(a.item_id));
  return roots[0]||null;
}

function setRootDeleted(rootId,deleted){
  if(deleted===isRootDeleted(rootId))return;
  if(deleted)deletedRootIds.add(Number(rootId));else deletedRootIds.delete(Number(rootId));saveDeletedBranches();
  const selectedRootId=selectedHeadId===null?null:rootIdForItem(selectedHeadId);
  if(deleted&&!showDeletedBranches&&selectedRootId===Number(rootId)){
    const replacement=selectReplacementRoot(Number(rootId));
    if(replacement){void selectBranchNode(replacement.item_id,replacement.branch_head_id);return}
    selectedHeadId=null;newRootSelected=true;
  }
  renderHistory();
}

function setBranchView(showDeleted){
  showDeletedBranches=showDeleted;
  const selectedRootId=selectedHeadId===null?null:rootIdForItem(selectedHeadId);
  if(!showDeleted&&selectedRootId!==null&&isRootDeleted(selectedRootId)){
    const replacement=selectReplacementRoot(selectedRootId);
    if(replacement){void selectBranchNode(replacement.item_id,replacement.branch_head_id);return}
    selectedHeadId=null;newRootSelected=true;renderHistory();return;
  }
  renderBranchPanel();
}

function renderBranchPanel(){
  updateBranchTabs();branchList.replaceChildren();
  const roots=visibleRoots().filter(root=>isRootDeleted(branchKey(root))===showDeletedBranches).sort((a,b)=>itemTime(rootLatestLeaf(b))-itemTime(rootLatestLeaf(a))||Number(b.item_id)-Number(a.item_id));
  if(!roots.length){const empty=document.createElement("div");empty.className="branch-empty";setI18nText(empty,showDeletedBranches?"branches.noDeleted":"branches.empty");branchList.appendChild(empty)}
  else{
    const groups=new Map();
    for(const root of roots){const group=groupForDate(itemTime(rootLatestLeaf(root)));const values=groups.get(group)||[];values.push(root);groups.set(group,values)}
    for(const group of ["today","yesterday","thisWeek","thisMonth","older"]){
      const values=groups.get(group);if(!values)continue;
      const section=document.createElement("section");section.className="branch-group";
      const title=document.createElement("div");title.className="branch-group-title";title.textContent="-- "+t("branches."+group)+" --";section.appendChild(title);
      for(const root of values)section.appendChild(renderBranchNode(root,0));
      branchList.appendChild(section);
    }
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
  const main=document.createElement("button");main.type="button";main.className="branch-row-main";main.style.paddingLeft=(6+depth*14)+"px";setI18nAttribute(main,"title","branches.select");
  const preview=document.createElement("span");preview.className="branch-preview";preview.textContent=depth===0?branchPreview(item):(item.content||t("branches.emptyMessage"));main.appendChild(preview);
  main.addEventListener("click",()=>{void selectBranchNode(item.item_id,item.branch_head_id)});row.appendChild(main);
  const children=logicalChildren(item.item_id);
  if(children.length){
    const toggle=document.createElement("button");toggle.type="button";toggle.className="branch-toggle";toggle.textContent=expandedNodes.has(item.item_id)?"⌄":"›";toggle.setAttribute("aria-expanded",String(expandedNodes.has(item.item_id)));setI18nAttribute(toggle,"aria-label",expandedNodes.has(item.item_id)?"branches.collapse":"branches.expand");setI18nAttribute(toggle,"title",expandedNodes.has(item.item_id)?"branches.collapse":"branches.expand");
    toggle.addEventListener("click",event=>{event.stopPropagation();if(expandedNodes.has(item.item_id))expandedNodes.delete(item.item_id);else expandedNodes.add(item.item_id);renderBranchPanel()});row.appendChild(toggle);
  }
  if(depth===0){
    const deleted=document.createElement("button");deleted.type="button";deleted.className="branch-delete";const branchId=branchKey(item);const isDeleted=isRootDeleted(branchId);deleted.textContent=isDeleted?"↩":"×";setI18nAttribute(deleted,"title",isDeleted?"branches.restore":"branches.hide");setI18nAttribute(deleted,"aria-label",isDeleted?"branches.restore":"branches.hide");deleted.addEventListener("click",event=>{event.stopPropagation();setRootDeleted(branchId,!isDeleted)});row.appendChild(deleted);
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
  const stickToBottom=shouldFollowMessagesBottom()&&!smoothScrollInProgress;const previousScrollTop=messagesEl.scrollTop;
  messagesPinnedToBottom=stickToBottom;
  if(!stickToBottom&&scrollFrame!==null){cancelAnimationFrame(scrollFrame);scrollFrame=null}
  hideTyping();hideCodeActSpinner();messagesEl.replaceChildren();activeStreams={};streamingPreviews={};codeactActiveEl=null;codeactStreamArgs="";codeactStreamToolId=null;lastWasCodeAct=false;
  for(const item of currentChain())if(isVisibleItem(item))renderItem(item);
  rememberCurrentSelection();renderBranchPanel();syncActionState();
  restoreMessagesScroll(stickToBottom,previousScrollTop);
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
    const previous=document.createElement("button");previous.type="button";previous.textContent="←";setI18nAttribute(previous,"title","message.previousBranch");setI18nAttribute(previous,"aria-label","message.previousBranch");previous.disabled=index<=0;previous.addEventListener("click",()=>selectBranchNode(siblings[index-1].item_id));nav.appendChild(previous);
    const count=document.createElement("span");count.className="branch-count";count.textContent=(index+1)+" / "+siblings.length;nav.appendChild(count);
    const next=document.createElement("button");next.type="button";next.textContent="→";setI18nAttribute(next,"title","message.nextBranch");setI18nAttribute(next,"aria-label","message.nextBranch");next.disabled=index<0||index>=siblings.length-1;next.addEventListener("click",()=>selectBranchNode(siblings[index+1].item_id));nav.appendChild(next);actions.appendChild(nav);
  }
  if(item.item_type==="input"){
    const regenerate=document.createElement("button");regenerate.type="button";regenerate.textContent="↻";setI18nAttribute(regenerate,"title","message.regenerate");setI18nAttribute(regenerate,"aria-label","message.regenerate");regenerate.addEventListener("click",()=>regenerateBranch(item));actions.appendChild(regenerate);
    const edit=document.createElement("button");edit.type="button";setI18nText(edit,"message.edit");setI18nAttribute(edit,"title","message.edit");edit.addEventListener("click",()=>editMessage(item,wrapper,content,actions));actions.appendChild(edit);
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
  if(role){const r=document.createElement("div");r.className="role";if(role==="Assistant")setI18nText(r,"message.assistant");else r.textContent=role;div.appendChild(r)}
  if(item)div.appendChild(createMessageMeta(item));
  const c=document.createElement("div");c.className="message-content";if(cls==="assistant")renderMarkdown(c,content);else c.textContent=content;div.appendChild(c);messagesEl.appendChild(div);return div;
}

function stripOutputMarkers(content){
  return String(content||"").replace(/\[(image|file):[^\]\r\n]+\]/gi,"").replace(/[ \t]+([,.;:!?])/g,"$1").trim();
}

function addReasoning(content){
  const details=document.createElement("details");details.className="msg reasoning_level";details.open=true;const summary=document.createElement("summary");setI18nText(summary,"message.reasoning");details.appendChild(summary);const c=document.createElement("div");c.className="message-content";renderMarkdown(c,content);details.appendChild(c);messagesEl.appendChild(details);return details;
}

function scheduleCodeHighlight(codeEl){
  if(codeEl._highlightScheduled)return;codeEl._highlightScheduled=true;
  const render=()=>{if(!document.body.contains(codeEl)){codeEl._highlightScheduled=false;return}if(typeof hljs==="undefined"){setTimeout(render,50);return}const stickToBottom=!smoothScrollInProgress&&shouldFollowMessagesBottom();const previousScrollTop=messagesEl.scrollTop;codeEl._highlightScheduled=false;delete codeEl.dataset.highlighted;hljs.highlightElement(codeEl);restoreMessagesScroll(stickToBottom,previousScrollTop)};
  requestAnimationFrame(render);
}

function createPrettyBlock(content,lang){
  const pre=document.createElement("pre");const codeEl=document.createElement("code");if(lang)codeEl.className="language-"+lang;let formatted=content;
  if(lang==="json"&&typeof content==="string")try{formatted=JSON.stringify(JSON.parse(content),null,2)}catch{}
  codeEl.textContent=formatted;pre.appendChild(codeEl);scheduleCodeHighlight(codeEl);return pre;
}

function updateCodeActElapsed(){
  if(codeactStartedAt!==null)codeactElapsedSeconds=Math.floor((performance.now()-codeactStartedAt)/1000);
  for(const element of document.querySelectorAll(".codeact-elapsed")){
    const seconds=element.classList.contains("codeact-current")?codeactElapsedSeconds:Number(element.dataset.elapsedSeconds||0);
    element.textContent=t("message.codeActElapsed",{seconds});
  }
}

function startCodeActTimer(){
  if(codeactTimer)return;
  codeactStartedAt=performance.now();codeactElapsedSeconds=0;updateCodeActElapsed();
  codeactTimer=setInterval(updateCodeActElapsed,250);
}

function stopCodeActTimer(elapsedSeconds=null){
  const hasElapsed=elapsedSeconds!==null&&elapsedSeconds!==undefined&&Number.isFinite(Number(elapsedSeconds))&&Number(elapsedSeconds)>=0;
  if(hasElapsed)codeactElapsedSeconds=Number(elapsedSeconds);else if(codeactStartedAt!==null)updateCodeActElapsed();
  if(codeactTimer){clearInterval(codeactTimer);codeactTimer=null}
  for(const element of document.querySelectorAll(".codeact-elapsed.codeact-current")){element.dataset.elapsedSeconds=String(codeactElapsedSeconds);element.classList.remove("codeact-current")}
  codeactStartedAt=null;
}

function showCodeActSpinner(){
  if(codeactSpinnerEl)return;startCodeActTimer();codeactSpinnerEl=document.createElement("div");codeactSpinnerEl.className="typing";codeactSpinnerEl.innerHTML='<span class="codeact-spinner"></span><span class="codeact-label"></span><span>.</span><span>.</span><span>.</span>';setI18nText(codeactSpinnerEl.querySelector(".codeact-label"),"message.codeAct");messagesEl.appendChild(codeactSpinnerEl);scrollToBottom();
}

function hideCodeActSpinner(elapsedSeconds=null){if(codeactSpinnerEl){codeactSpinnerEl.remove();codeactSpinnerEl=null}stopCodeActTimer(elapsedSeconds)}

function addCodeActCall(args){
  let code;if(typeof args==="string"){try{const parsed=JSON.parse(args);code=parsed.code||args}catch{code=args}}else code=args&&typeof args.code==="string"?args.code:JSON.stringify(args,null,2);
  showCodeActSpinner();const details=document.createElement("details");details.className="msg codeact";details.open=true;const summary=document.createElement("summary");summary.className="codeact-title";summary.innerHTML='<span class="codeact-label"></span><span class="codeact-elapsed codeact-current"></span>';setI18nText(summary.querySelector(".codeact-label"),"message.codeAct");updateCodeActElapsed();details.appendChild(summary);details.appendChild(createPrettyBlock(code,"python"));messagesEl.appendChild(details);codeactActiveEl=details;lastWasCodeAct=true;scrollToBottom();
}

function decodePartialCodeArg(raw){
  const key=raw.match(/"code"\s*:\s*"/);if(!key||key.index===undefined)return raw;let index=key.index+key[0].length;let result="";
  while(index<raw.length){const char=raw[index++];if(char==='"')return result;if(char!=="\\"){result+=char;continue}if(index>=raw.length)break;const escaped=raw[index++];if(escaped==="n")result+="\n";else if(escaped==="r")result+="\r";else if(escaped==="t")result+="\t";else if(escaped==="b")result+="\b";else if(escaped==="f")result+="\f";else if(escaped==="u"){const hex=raw.slice(index,index+4);if(hex.length<4||!/^[0-9a-fA-F]{4}$/.test(hex))break;result+=String.fromCharCode(parseInt(hex,16));index+=4}else if(escaped==='"'||escaped==="\\"||escaped==="/")result+=escaped;else result+=escaped}
  return result;
}

function codeActPreviewContent(raw){try{const parsed=JSON.parse(raw);if(parsed&&typeof parsed.code==="string")return parsed.code}catch{}return decodePartialCodeArg(raw)}

function streamPreviewKey(data){
  const meta=data?.meta||{};const toolId=meta.tool_call_id;
  return toolId?"tool_call:"+toolId:data?.stream_id||data?.item_type||"stream";
}

/** @param {StreamEvent} data */
function updateCodeActPreview(data){
  const meta=data.meta||{};if(meta.tool_name!=="execute")return false;const streamKey=data.stream_id||meta.tool_call_id||null;
  if(codeactStreamToolId&&streamKey&&streamKey!==codeactStreamToolId){codeactStreamArgs="";codeactActiveEl=null}
  if(!codeactActiveEl)addCodeActCall({code:""});codeactStreamToolId=streamKey;codeactStreamArgs+=data.content||"";const code=codeActPreviewContent(codeactStreamArgs);const codeEl=codeactActiveEl&&codeactActiveEl.querySelector("pre code");
  if(codeEl)codeEl.textContent=code;streamingPreviews[streamPreviewKey(data)]=codeactActiveEl;return true;
}

function finishCodeActSession(content,elapsedSeconds=null){
  updateCodeActElapsed();hideCodeActSpinner(elapsedSeconds);if(codeactActiveEl){const codeEl=codeactActiveEl.querySelector("pre code");if(codeEl)scheduleCodeHighlight(codeEl);const spinner=codeactActiveEl.querySelector(".codeact-spinner");if(spinner)spinner.remove();const summary=codeactActiveEl.querySelector("summary");if(summary){const label=summary.querySelector(".codeact-label");if(label)setI18nText(label,"message.codeAct");updateCodeActElapsed()}codeactActiveEl=null}
  if(content){const details=document.createElement("details");details.className="msg tool-result";details.open=true;const summary=document.createElement("summary");setI18nText(summary,"message.result");details.appendChild(summary);details.appendChild(createPrettyBlock(content,null));messagesEl.appendChild(details);scrollToBottom()}
  codeactStreamArgs="";codeactStreamToolId=null;lastWasCodeAct=false;
}

function addToolCall(name,args){
  if(name==="execute"){addCodeActCall(args);return}const argsString=typeof args==="string"?args:JSON.stringify(args,null,2);const hasArgs=typeof args==="string"?args.length>0:Object.keys(args||{}).length>0;
  if(!hasArgs||!argsString.includes("\n")){const div=document.createElement("div");div.className="msg tool-call";const label=document.createElement("div");setI18nText(label,"message.tool",{name});div.appendChild(label);if(hasArgs)div.appendChild(createPrettyBlock(argsString,"json"));messagesEl.appendChild(div);return}
  const details=document.createElement("details");details.className="msg tool-call";details.open=true;const summary=document.createElement("summary");setI18nText(summary,"message.tool",{name});details.appendChild(summary);details.appendChild(createPrettyBlock(argsString,"json"));messagesEl.appendChild(details);
}

function addToolResult(content){
  const value=content===undefined||content===null?"":typeof content==="string"?content:JSON.stringify(content,null,2);
  if(!value.includes("\n")){const div=document.createElement("div");div.className="msg tool-result";const label=document.createElement("div");setI18nText(label,"message.toolResult");div.appendChild(label);div.appendChild(createPrettyBlock(value,null));messagesEl.appendChild(div);return}
  const details=document.createElement("details");details.className="msg tool-result";details.open=true;const summary=document.createElement("summary");setI18nText(summary,"message.toolResult");details.appendChild(summary);let lang=null;try{JSON.parse(value);lang="json"}catch{}details.appendChild(createPrettyBlock(value,lang));messagesEl.appendChild(details);
}

function addImageOutput(content){return addAttachmentMessage(content,"image")}
function addFileOutput(content){return addAttachmentMessage(content,"file")}

function addPlaceholder(type){const div=document.createElement("div");div.className="msg assistant";const placeholder=document.createElement("div");placeholder.className="placeholder";const key=type==="image_input"?"message.imageInput":type==="file_input"?"message.fileInput":"message.output";setI18nText(placeholder,key);div.appendChild(placeholder);messagesEl.appendChild(div)}
function addError(text){addMessage("error",text,null)}

function showTyping(){
  if(typingIndicator)return;typingIndicator=document.createElement("div");typingIndicator.className="typing";typingIndicator.innerHTML='<span class="typing-label"></span><span>.</span><span>.</span><span>.</span>';setI18nText(typingIndicator.querySelector(".typing-label"),"message.thinking");messagesEl.appendChild(typingIndicator);scrollToBottom();
}

function hideTyping(){if(typingIndicator){typingIndicator.remove();typingIndicator=null}}

function setProcessing(on,streamId=null){
  activeStreamId=on?streamId:null;setI18nText(sendBtn,on?"chat.cancel":"chat.send");sendBtn.classList.toggle("cancel",on);updateSendButton();setUiStatus(on?"processing":"ready");if(!on)hideTyping();syncActionState();
}

function syncActionState(){
  const busy=Boolean(activeStreamId);for(const button of document.querySelectorAll(".message-actions button, #new-branch-btn, .branch-row button"))button.disabled=busy;
}

/** @param {DialogItem} item */
function renderItem(item){
  hideTyping();
  const previewKeys=[item.item_type];
  if(item.item_type==="tool_call"){
    try{const toolCall=JSON.parse(item.content);if(toolCall.tool_call_id)previewKeys.push("tool_call:"+toolCall.tool_call_id)}catch{}
  }
  let itemToolCallId=null;
  if(item.item_type==="tool_call"){
    try{itemToolCallId=JSON.parse(item.content).tool_call_id||null}catch{}
  }
  for(const key of previewKeys){const preview=streamingPreviews[key];if(preview){preview.remove();delete streamingPreviews[key]}}
  for(const key of Object.keys(activeStreams)){const stream=activeStreams[key];const sameTool=item.item_type!=="tool_call"||!itemToolCallId||!stream.tool_call_id||stream.tool_call_id===itemToolCallId;if(stream.item_type===item.item_type&&stream.previous_item_id===item.previous_item_id&&sameTool){stream.element.remove();delete activeStreams[key]}}
  if(item.meta?.is_tool_call_result&&!(["image_input","file_input"].includes(item.item_type))){addToolResult(item.content||"");return}
  switch(item.item_type){
    case "input":
    case "image_input":
    case "file_input":
      if(item.role==="user")messagesEl.appendChild(createUserEntry(item));else addPlaceholder(item.item_type);break;
    case "reasoning_level":addReasoning(item.content);break;
    case "tool_call":try{const toolCall=JSON.parse(item.content);addToolCall(toolCall.tool_name||"unknown",toolCall.tool_args||{})}catch{addToolCall("tool",item.content)}break;
    case "tool_call_result":{const elapsedSeconds=item.meta?.codeact?.elapsed_seconds;const hasCodeActElapsed=elapsedSeconds!==null&&elapsedSeconds!==undefined&&Number.isFinite(Number(elapsedSeconds));if(lastWasCodeAct||hasCodeActElapsed){try{const result=JSON.parse(item.content);finishCodeActSession(result.content,elapsedSeconds)}catch{finishCodeActSession(item.content,elapsedSeconds)}}else{try{const result=JSON.parse(item.content);addToolResult(result.content)}catch{addToolResult(item.content)}}break}
    case "output":addAssistantOutput(item);break;
     case "image_output":addImageOutput(item.content);break;
    case "file_output":addFileOutput(item.content);break;
    default:addMessage("assistant",item.content,"Assistant",item);
  }
}

/** @param {StreamEvent} data */
function handleStreamChunk(data){
  if(selectedHeadId!==null&&data.previous_item_id!==null&&data.previous_item_id!==selectedHeadId)return;
  const stickToBottom=!smoothScrollInProgress&&shouldFollowMessagesBottom();const previousScrollTop=messagesEl.scrollTop;
  hideTyping();const chunkType=data.item_type||"output";
  if(chunkType==="tool_call"&&updateCodeActPreview(data)){restoreMessagesScroll(stickToBottom,previousScrollTop);return}
  const streamId=data.stream_id||chunkType;let stream=activeStreams[streamId];
  setUiStatus("streaming");
  if(!stream){let element;if(chunkType==="reasoning_level")element=addReasoning("");else if(chunkType==="tool_call"){element=document.createElement("details");element.className="msg tool-call";element.open=true;const summary=document.createElement("summary");setI18nText(summary,"message.toolPlaceholder");element.appendChild(summary);const content=document.createElement("div");element.appendChild(content);messagesEl.appendChild(element)}else element=addMessage("assistant","","Assistant");stream={element,item_type:chunkType,previous_item_id:data.previous_item_id,tool_call_id:data.meta?.tool_call_id||null,text:""};activeStreams[streamId]=stream}
  if(chunkType==="tool_call"&&data.meta?.tool_call_id)stream.tool_call_id=data.meta.tool_call_id;stream.text+=(data.content||"");const contentEl=stream.element.querySelector("div:last-child")||stream.element;
  if(chunkType==="output"||chunkType==="reasoning_level")renderMarkdown(contentEl,stripOutputMarkers(stream.text));else contentEl.textContent=stream.text;
  restoreMessagesScroll(stickToBottom,previousScrollTop);
}

async function submitMessage(text,parentId,branch=null,attachments=[]){
  if(!authToken){showAuth();return false}
  if(!eventsReady){setUiStatus("connecting");return false}
  if(activeStreamId)return false;
  const previousItemId=parentId===null||parentId===undefined?null:parentId;
  pendingBranch=branch;pendingMessage={parentId:previousItemId,content:text,attachments};pendingRoot=!branch&&previousItemId===null;pendingRootContent=pendingRoot?text:"";setUiStatus("sending");sendBtn.disabled=true;
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/api/messages?stream=1"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:text,attachments:attachments.map(attachmentPayload),previous_item_id:previousItemId,timezone:browserTimezone()})});
    if(unauthorized){setProcessing(false);clearPendingMessage();return false}
    if(!response.ok){setProcessing(false);addError(localizedServerMessage(data)||t("error.messageRejected"));clearPendingMessage();return false}
    setProcessing(true,data.stream_id);showTyping();return true;
  }catch(error){addError(t("error.network",{message:error.message}));clearPendingMessage();setProcessing(false);return false}
}

async function send(){
  if(!eventsReady){setUiStatus("connecting");return}
  const text=inputEl.value.trim();if(activeStreamId)return;
  const uploading=pendingAttachments.some(attachment=>attachment.status==="uploading");if(uploading){setUiStatus("waitUploads");return}
  const failed=pendingAttachments.some(attachment=>attachment.status!=="ready");if(failed){setUiStatus("removeFailedUploads");return}
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
  }catch(error){addError(t("error.cancelRequest",{message:error.message}))}
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
  const cancel=document.createElement("button");cancel.type="button";setI18nText(cancel,"common.cancel");cancel.addEventListener("click",()=>renderHistory());editActions.appendChild(cancel);
  const save=document.createElement("button");save.type="button";save.className="primary";setI18nText(save,"common.save");save.addEventListener("click",async()=>{const text=textarea.value.trim();if(!text){textarea.focus();return}save.disabled=true;cancel.disabled=true;const sent=await submitMessage(text,item.previous_item_id,{parentId:item.previous_item_id,content:text});if(!sent){save.disabled=false;cancel.disabled=false}else closeBranchPanel()});editActions.appendChild(save);content.appendChild(editActions);textarea.focus();textarea.setSelectionRange(textarea.value.length,textarea.value.length);
  textarea.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==="Enter"){event.preventDefault();save.click()}});
}

function newBranch(){
  if(activeStreamId)return;
  newRootSelected=true;selectedHeadId=null;
  clearPendingMessage();renderHistory();inputEl.focus();closeBranchPanel();
}

/** @param {StreamEvent} data */
async function handleServerEvent(data){
  if(data.type==="stream_started"){if(typeof data.stream_id==="string"){setProcessing(true,data.stream_id);showTyping()}}
  else if(data.type==="stream_chunk")handleStreamChunk(data);
  else if(data.type==="dialog_item")await applyDialogItem(data);
  else if(data.type==="typing"){
    if(data.active){showTyping();setUiStatus("processing")}else hideTyping();
  }
  else if(data.type==="message_done"){if(!activeStreamId||data.stream_id===activeStreamId){setProcessing(false);await loadHistory()}}
  else if(data.type==="error")addError(localizedServerMessage(data)||t("error.server"));
}

function historyRequestUrl(branchHeadId=null){
  const params=new URLSearchParams();params.set("heads","1");
  const requested=branchHeadId??selectedHeadId;params.set("branch_head",requested===null||requested===undefined?"latest":String(requested));
  return serverUrl("/api/history?")+params.toString();
}

async function loadHistory(preferredHeadId=null){
  const knownItemIds=new Set(itemsById.keys());
  const requestedHeadId=preferredHeadId??selectedHeadId;
  const {response,data,unauthorized}=await authJson(historyRequestUrl(requestedHeadId));
  if(unauthorized)return
  if(!response.ok)throw new Error(t("error.historyRequest"));
  const previousSelected=selectedHeadId;
  historyHeads=Array.isArray(data.heads)?data.heads.filter(head=>head&&head.item_id!==null&&head.item_id!==undefined):[];
  const incomingItems=Array.isArray(data.items)?data.items:[];
  rebuildGraph(incomingItems);
  const responseHeadId=Number.isInteger(data.current_head_id)?data.current_head_id:null;
  const preferredItem=typeof requestedHeadId==="number"?itemsById.get(requestedHeadId):null;
  const pendingItem=pendingMessage?[...itemsById.values()].filter(item=>!knownItemIds.has(item.item_id)&&pendingItemMatches(item)).sort(compareItems).pop():null;
  const keepSelection=historyLoaded&&!pendingMessage&&previousSelected!==null&&isVisibleItem(itemsById.get(previousSelected));
  if(pendingItem){selectedHeadId=latestBranchItemId(pendingItem.item_id)||pendingItem.item_id;clearPendingMessage()}
  else if(responseHeadId!==null)selectedHeadId=responseHeadId;
  else if(preferredItem)selectedHeadId=latestBranchItemId(preferredItem.item_id)||preferredItem.item_id;
  else if(keepSelection)selectedHeadId=previousSelected;
  else if(!historyLoaded&&!pendingMessage)selectedHeadId=latestGlobalItemId();
  else if(!pendingMessage&&selectedHeadId!==null&&!itemsById.has(selectedHeadId))selectedHeadId=latestGlobalItemId();
  historyLoaded=true;rememberCurrentSelection();renderHistory();
}

function handleEventStream(){
  const request=new XMLHttpRequest();eventsRequest=request;let offset=0;let buffer="";let opened=false;let settled=false;let processing=Promise.resolve();let resolveDone;let rejectDone;
  const done=new Promise((resolve,reject)=>{resolveDone=resolve;rejectDone=reject});
  const finish=error=>{if(settled)return;settled=true;if(error)rejectDone(error);else resolveDone()};
  const consume=()=>{
    const text=request.responseText.slice(offset);offset=request.responseText.length;if(!text)return;
    processing=processing.then(async()=>{buffer+=text;const lines=buffer.split("\n");buffer=lines.pop()||"";for(const line of lines){if(!line.startsWith("data: "))continue;try{const data=JSON.parse(line.slice(6));if(data.type!=="done")await handleServerEvent(data)}catch{}}});
  };
  const finishRequest=()=>{consume();processing.then(()=>finish(request.status===0?new Error("Events stream disconnected"):null)).catch(finish)};
  request.onreadystatechange=()=>{
    if(request.readyState===XMLHttpRequest.HEADERS_RECEIVED&&!opened){
      if(request.status===401){expireSession();request.abort();finish(new Error("Unauthorized"));return}
      if(request.status<200||request.status>=300){setServerConnected(false);request.abort();finish(new Error(`Events stream returned HTTP ${request.status}`));return}
      opened=true;setServerConnected(true);setEventsReady(true);
    }
    if(request.readyState===XMLHttpRequest.LOADING)consume();
    if(request.readyState===XMLHttpRequest.DONE)finishRequest();
  };
  request.onerror=()=>finish(new Error("Events stream failed"));
  request.onabort=()=>{const error=new Error("Events stream aborted");if(eventsAbortController?.signal.aborted)error.name="AbortError";finish(error)};
  request.open("GET",serverUrl("/api/events"),true);
  for(const [name,value] of Object.entries(authHeaders()))request.setRequestHeader(name,value);
  request.setRequestHeader("Accept","text/event-stream");
  if(eventsAbortController){eventsAbortController.signal.addEventListener("abort",()=>request.abort(),{once:true})}
  request.send();
  return done.finally(()=>{if(eventsRequest===request)eventsRequest=null});
}

async function eventsLoop(){
  while(authToken){
    setEventsReady(false);
    try{
      eventsAbortController=new AbortController();const streamPromise=handleEventStream();
      try{await loadHistory()}catch(error){console.error("[CommaMatrix UI] event history refresh failed",error)}
      await streamPromise;
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
  try{await loadHistory()}catch(error){addError(t("error.couldNotLoadHistory",{message:error.message}))}
  startEvents();
  return true;
}

function logout(){clearAuth();showAuth()}
function messagesAreAtBottom(){return messagesEl.scrollHeight-messagesEl.clientHeight-messagesEl.scrollTop<=SCROLL_BOTTOM_THRESHOLD}
function shouldFollowMessagesBottom(){return messagesPinnedToBottom||messagesAreAtBottom()}
function updateScrollBottomButton(){const visible=!smoothScrollInProgress&&!messagesPinnedToBottom&&!messagesAreAtBottom();scrollBottomBtn.classList.toggle("visible",visible);scrollBottomBtn.classList.toggle("is-hidden",!visible);scrollBottomBtn.setAttribute("aria-hidden",String(!visible));scrollBottomBtn.tabIndex=visible?0:-1}
function handleMessagesScroll(){const atBottom=messagesAreAtBottom();if(atBottom){smoothScrollInProgress=false;messagesPinnedToBottom=true;userScrollPending=false}else if(!smoothScrollInProgress&&userScrollPending){messagesPinnedToBottom=false;userScrollPending=false}updateScrollBottomButton()}
function markUserScroll(){userScrollPending=true;cancelSmoothScroll()}
function handleMessagesPointerDown(event){cancelSmoothScroll();const rect=messagesEl.getBoundingClientRect();const scrollbarWidth=messagesEl.offsetWidth-messagesEl.clientWidth;if(scrollbarWidth>0&&event.clientX>=rect.right-scrollbarWidth)userScrollPending=true}
function restoreMessagesScroll(stickToBottom,previousScrollTop){if(stickToBottom){messagesPinnedToBottom=true;scrollToBottom({force:true});return}if(scrollFrame!==null){cancelAnimationFrame(scrollFrame);scrollFrame=null}messagesPinnedToBottom=false;messagesEl.scrollTop=previousScrollTop;updateScrollBottomButton()}
function cancelSmoothScroll(){if(!smoothScrollInProgress)return;smoothScrollInProgress=false;messagesPinnedToBottom=false;updateScrollBottomButton()}
function scrollToBottom({force=false,smooth=false}={}){
  if(force){messagesPinnedToBottom=true;smoothScrollInProgress=false;updateScrollBottomButton()}
  if(!force&&!messagesPinnedToBottom){updateScrollBottomButton();return}
  if(scrollFrame!==null)cancelAnimationFrame(scrollFrame);
  scrollFrame=requestAnimationFrame(()=>{
    scrollFrame=null;
    if(!force&&!messagesPinnedToBottom){updateScrollBottomButton();return}
    if(smooth){smoothScrollInProgress=true;messagesEl.scrollTo({top:messagesEl.scrollHeight,behavior:"smooth"});if(messagesAreAtBottom())smoothScrollInProgress=false}else{smoothScrollInProgress=false;messagesEl.scrollTop=messagesEl.scrollHeight}
    messagesPinnedToBottom=true;updateScrollBottomButton();
  });
}
function closeBranchPanel(){document.body.classList.remove("branch-panel-open")}
function openBranchPanel(){document.body.classList.add("branch-panel-open")}
function adjustInputHeight(){inputEl.style.height="auto";const maxHeight=window.innerHeight*.33;inputEl.style.height=Math.min(inputEl.scrollHeight,maxHeight)+"px"}
function updateScrollBottomPosition(){chatColumn.style.setProperty("--input-area-height",inputArea.offsetHeight+attachmentPreviewsEl.offsetHeight+"px")}

function setupPasswordToggle(button){
  const input=document.getElementById(button.dataset.passwordTarget);
  if(!input)return
  button.addEventListener("click",()=>{const visible=input.type==="text";input.type=visible?"password":"text";button.dataset.visible=String(!visible);setI18nText(button,visible?"auth.show":"auth.hide");button.setAttribute("aria-pressed",String(!visible))});
}

function closeAttachmentOverlay(){attachmentOverlay.classList.add("hidden")}
function openAttachmentOverlay(){if(!authToken){showAuth();return}uploadFileChoice.disabled=!fileUploadAllowed;closeLinkOverlay();attachmentOverlay.classList.remove("hidden")}
function closeLinkOverlay(){linkOverlay.classList.add("hidden");linkError.textContent=""}
function openLinkOverlay(){if(!authToken){showAuth();return}closeAttachmentOverlay();linkForm.reset();linkError.textContent="";linkOverlay.classList.remove("hidden");linkInput.focus()}
function chooseUpload(){closeAttachmentOverlay();if(!fileUploadAllowed){showUploadBlocked();return}fileInput.click()}
function closeUsernameOverlay(){usernameOverlay.classList.add("hidden")}
function openUsernameOverlay(){if(!authToken){showAuth();return}setHeaderMenuOpen(false);usernameError.textContent="";usernameInput.value=currentUser?.username||"";usernameOverlay.classList.remove("hidden");usernameInput.focus();usernameInput.select()}
async function submitUsername(event){
  event.preventDefault();usernameError.textContent="";
  const validation=validateUsername(usernameInput.value);
  if(validation.errorKey){usernameError.textContent=t(validation.errorKey);return}
  usernameInput.value=validation.value;
  try{
    const {response,data,unauthorized}=await authJson(serverUrl("/api/username"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:validation.value})});
    if(unauthorized)return;
    if(!response.ok){usernameError.textContent=localizedAuthError(data,"error.usernameChange");return}
    currentUser={...currentUser,username:data.username||validation.value};userLabel.textContent=currentUser.username;closeUsernameOverlay();
  }catch(error){usernameError.textContent=t("error.network",{message:error.message})}
}

async function registerOrLogin(event){
  event.preventDefault();let username=authUsername.value.trim();const password=authPassword.value;authError.textContent="";
  if(!password){authError.textContent=t("error.credentialsRequired");return}
  if(authMode==="register"){const validation=validateUsername(username);if(validation.errorKey){authError.textContent=t(validation.errorKey);return}username=validation.value}else if(!username){authError.textContent=t("error.credentialsRequired");return}
  if(authMode==="register"&&password!==authConfirm.value){authError.textContent=t("error.passwordMismatch");return}
  authSubmit.disabled=true;
  try{
    if(authMode==="register"){
      const response=await fetch(serverUrl("/api/register"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:inviteToken,username,password})});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=localizedAuthError(data,"error.registration");return}history.replaceState({},"",location.pathname);inviteToken=null;authMode="login";setAuthMode("login");authUsername.value=username;authPassword.value="";authError.textContent=t("error.accountCreated");return;
    }
    const response=await fetch(serverUrl("/api/login"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});const data=await response.json().catch(()=>({}));if(!response.ok){authError.textContent=data.detail||t("error.signIn");return}authToken=data.access_token;localStorage.setItem("commamatrix_auth_token",authToken);await loadCurrentUser();authForm.reset();
  }catch(error){console.error("[CommaMatrix UI] auth request failed",error);authError.textContent=t("error.network",{message:error.message})}finally{authSubmit.disabled=false}
}

document.querySelectorAll(".password-toggle").forEach(setupPasswordToggle);
headerMenuBtn.addEventListener("click",()=>setHeaderMenuOpen(!document.body.classList.contains("header-menu-open")));
serverStatusBtn.addEventListener("click",()=>{const visible=serverStatusPanel.classList.contains("visible");if(!visible&&!statusPanelOverride&&!serverStatusMessages.length)return;setStatusPanelVisible(!visible)});
usernameBtn.addEventListener("click",openUsernameOverlay);
document.getElementById("username-cancel").addEventListener("click",closeUsernameOverlay);
usernameForm.addEventListener("submit",event=>{void submitUsername(event)});
passwordBtn.addEventListener("click",()=>{setHeaderMenuOpen(false);passwordError.textContent="";passwordForm.reset();passwordOverlay.classList.remove("hidden")});
document.getElementById("password-cancel").addEventListener("click",()=>passwordOverlay.classList.add("hidden"));
passwordForm.addEventListener("submit",async event=>{event.preventDefault();passwordError.textContent="";const next=document.getElementById("new-password").value;if(next!==document.getElementById("new-password-confirm").value){passwordError.textContent=t("error.passwordMismatch");return}try{const {response,data,unauthorized}=await authJson(serverUrl("/api/password"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({old_password:document.getElementById("old-password").value,new_password:next})});if(unauthorized)return;if(!response.ok){passwordError.textContent=data.detail||t("error.passwordChange");return}passwordOverlay.classList.add("hidden")}catch(error){passwordError.textContent=t("error.network",{message:error.message})}});
inviteBtn.addEventListener("click",async()=>{setHeaderMenuOpen(false);const {response,data,unauthorized}=await authJson(serverUrl("/api/invite"),{method:"POST"});if(unauthorized)return;if(!response.ok){addError(data.detail||t("error.invitation"));return}inviteLink=data.url||"";inviteOverlay.classList.remove("hidden")});
document.getElementById("invite-copy").addEventListener("click",async function(){await navigator.clipboard.writeText(inviteLink);setI18nText(this,"invite.copied");setTimeout(()=>setI18nText(this,"invite.copy"),1200)});
document.getElementById("invite-close").addEventListener("click",()=>inviteOverlay.classList.add("hidden"));
attachmentCancel.addEventListener("click",closeAttachmentOverlay);
insertLinkChoice.addEventListener("click",openLinkOverlay);
uploadFileChoice.addEventListener("click",chooseUpload);
linkCancel.addEventListener("click",closeLinkOverlay);
linkForm.addEventListener("submit",event=>{event.preventDefault();const url=httpUrl(linkInput.value);if(!url){linkError.textContent=t("error.invalidUrl");return}addExternalLink(url);closeLinkOverlay()});
languageBtn.addEventListener("click",()=>setLocale(locale==="ru"?"en":"ru"));logoutBtn.addEventListener("click",logout);authForm.addEventListener("submit",event=>{void registerOrLogin(event)});sendBtn.addEventListener("click",()=>{if(activeStreamId)void cancelProcessing();else void send()});attachBtn.addEventListener("click",openAttachmentOverlay);fileInput.addEventListener("change",event=>{uploadFiles(event.target.files);fileInput.value=""});inputArea.addEventListener("drop",handleDrop);window.addEventListener("dragenter",handlePageDragEnter);window.addEventListener("dragover",handlePageDragOver);window.addEventListener("dragleave",handlePageDragLeave);window.addEventListener("drop",handlePageDrop);window.addEventListener("dragend",resetPageDrag);newBranchBtn.addEventListener("click",newBranch);activeBranchesBtn.addEventListener("click",()=>setBranchView(false));deletedBranchesBtn.addEventListener("click",()=>setBranchView(true));branchOpenBtn.addEventListener("click",openBranchPanel);branchCloseBtn.addEventListener("click",closeBranchPanel);branchBackdrop.addEventListener("click",closeBranchPanel);
inputEl.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();void send()}});inputEl.addEventListener("input",adjustInputHeight);messagesEl.addEventListener("scroll",handleMessagesScroll,{passive:true});messagesEl.addEventListener("wheel",markUserScroll,{passive:true});messagesEl.addEventListener("touchstart",markUserScroll,{passive:true});messagesEl.addEventListener("pointerdown",handleMessagesPointerDown);scrollBottomBtn.addEventListener("click",()=>scrollToBottom({force:true,smooth:true}));window.addEventListener("resize",()=>{adjustInputHeight();updateScrollBottomPosition();handleMessagesScroll()});if(typeof ResizeObserver!=="undefined")new ResizeObserver(updateScrollBottomPosition).observe(inputArea);updateScrollBottomPosition();handleMessagesScroll();

applyTranslations();updateLanguageButton();setAuthMode(authMode);renderBranchPanel();if(inviteToken){clearAuth();showAuth()}else void loadCurrentUser();
})();







































