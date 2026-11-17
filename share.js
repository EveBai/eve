const copyButton = document.querySelector('#copy-share');
const shareStatus = document.querySelector('#share-status');

copyButton?.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
    shareStatus.textContent = '链接已复制，可以发给朋友了。';
  } catch {
    shareStatus.textContent = '可以直接复制浏览器地址栏里的链接。';
  }
});
