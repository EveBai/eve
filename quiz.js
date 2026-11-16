const roles = {
  spark: ["气氛点火员", "你常常用一句话把大家带进状态。你的热情让朋友更容易放开玩。", "哪次聚会是被一句话救活的？"],
  anchor: ["贴心观察员", "你很容易留意到谁刚刚没接上话。朋友和你在一起，安静也不会尴尬。", "朋友做过哪件小事，让你觉得被照顾到了？"],
  guide: ["路线规划员", "你擅长把「改天一起玩」变成一场真的聚会。朋友可以放心把下一步交给你。", "如果下一次聚会只定一个规则，你会选什么？"],
  wildcard: ["意外惊喜担当", "你总能带来一点计划外的乐趣。朋友想起这场聚会时，也许会先想起你的奇怪点子。", "你最想在聚会里加一个什么奇怪环节？"],
};

const questions = [
  ["群里有人说「周末出来玩」，你更可能？", [
    ["先抛一个有意思的话题，把大家喊出来", "spark"],
    ["问问最近很忙的朋友有没有空", "anchor"],
    ["发个投票，把时间地点确定下来", "guide"],
    ["提议大家带一件家里最离谱的东西", "wildcard"],
  ]],
  ["聚会刚开始，大家有点拘谨。你会？", [
    ["找一个落单的朋友聊几句", "anchor"],
    ["拿出准备好的小游戏", "guide"],
    ["顺手给桌上的零食起一堆奇怪名字", "wildcard"],
    ["讲个好笑的近况，让大家接着聊", "spark"],
  ]],
  ["原本订的店临时不开门，你会？", [
    ["开始看附近还有哪些地方能去", "guide"],
    ["把等位变成一场拍照挑战", "wildcard"],
    ["笑着提议大家先玩个猜谜", "spark"],
    ["先确认大家饿不饿、累不累", "anchor"],
  ]],
  ["拍合照的时候，你最常做什么？", [
    ["带头比一个奇怪的姿势", "wildcard"],
    ["倒数三秒，负责喊大家笑", "spark"],
    ["确认每个人都进了镜头", "anchor"],
    ["找光线、支手机，把照片拍好", "guide"],
  ]],
  ["聚会散场后，你更可能发什么？", [
    ["今晚最好笑的那一幕", "spark"],
    ["一句「到家了吗」", "anchor"],
    ["拍好的照片和下次见面的时间", "guide"],
    ["一张只有现场的人才看得懂的图", "wildcard"],
  ]],
];

const storageKey = "happy-quiz.friend-role.v1";
const panel = document.querySelector("#panel");
const content = document.querySelector("#panel-content");
const cards = document.querySelectorAll(".card");
const filters = document.querySelectorAll("[data-filter]");
let answers = [];

function heading(title) {
  content.replaceChildren();
  const element = document.createElement("h2");
  element.id = "panel-title";
  element.textContent = title;
  content.append(element);
}

function paragraph(text) {
  const element = document.createElement("p");
  element.textContent = text;
  content.append(element);
}

function button(text, action, className = "primary") {
  const element = document.createElement("button");
  element.type = "button";
  element.className = className;
  element.textContent = text;
  element.addEventListener("click", action);
  return element;
}

function readHistory() {
  try {
    const records = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(records)
      ? records.filter(record => record && Object.hasOwn(roles, record.role) && Number.isFinite(record.time))
      : [];
  } catch {
    return [];
  }
}

function showQuestion() {
  const [prompt, choices] = questions[answers.length];
  heading(prompt);
  paragraph(`第 ${answers.length + 1} 题，共 ${questions.length} 题`);
  const list = document.createElement("div");
  list.className = "choices";
  for (const [label, role] of choices) {
    list.append(button(label, () => {
      answers.push(role);
      if (answers.length === questions.length) finish();
      else showQuestion();
    }, "choice"));
  }
  content.append(list);
  if (answers.length) {
    content.append(button("返回上一题", () => {
      answers.pop();
      showQuestion();
    }, "back"));
  }
  list.firstElementChild.focus();
}

function finish() {
  const counts = new Map();
  for (const role of answers) counts.set(role, (counts.get(role) || 0) + 1);
  const [role] = [...counts].sort((a, b) => b[1] - a[1])[0];
  const [title, description, conversation] = roles[role];
  heading(title);
  paragraph(description);
  paragraph(`聊天话题 · ${conversation}`);
  paragraph("这是一份趣味结果，看看朋友会怎么描述你。");
  try {
    const records = [{ role, time: Date.now() }, ...readHistory()].slice(0, 20);
    localStorage.setItem(storageKey, JSON.stringify(records));
  } catch {
    paragraph("此浏览器暂时无法保存测试记录。");
  }
  const retry = button("再玩一次", start);
  content.append(retry);
  retry.focus();
}

function start() {
  answers = [];
  if (!panel.open) panel.showModal();
  showQuestion();
}

function selectFilter(category) {
  for (const filter of filters) filter.setAttribute("aria-pressed", String(filter.dataset.filter === category));
  for (const card of cards) card.hidden = category !== "all" && category !== card.dataset.category;
}

for (const filter of filters) filter.addEventListener("click", () => selectFilter(filter.dataset.filter));
document.querySelector(".hero a")?.addEventListener("click", () => selectFilter("all"));
document.querySelector("#start")?.addEventListener("click", start);
document.querySelector("#history")?.addEventListener("click", () => {
  heading("我的试玩记录");
  const records = readHistory();
  if (!records.length) paragraph("完成一次测试后，结果会出现在这里。");
  else {
    paragraph("以下记录保存在当前浏览器。");
    for (const { role, time } of records) {
      paragraph(`${new Date(time).toLocaleString("zh-CN")} · ${roles[role][0]}`);
    }
  }
  panel.showModal();
});
