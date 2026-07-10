// 宠物管理
export function loadPet() {
  fetch('/api/pet/status')
    .then(r => r.json())
    .then(data => {
      if (!data.found) {
        document.getElementById('pet-status').innerHTML =
          '<div style="text-align:center;padding:40px"><p>尚未领养宠物</p><button class="btn btn-primary" onclick="adoptPet()">领养宠物</button></div>';
        return;
      }

      document.getElementById('pet-name').textContent = data.name;
      document.getElementById('pet-level').textContent = `Lv.${data.level} · ${data.style} 风格`;
      document.getElementById('pet-mood').style.width = data.mood + '%';
      document.getElementById('pet-hunger').style.width = data.hunger + '%';
      document.getElementById('pet-energy').style.width = data.energy + '%';
      document.getElementById('pet-intellect').style.width = data.intellect + '%';

      if (data.ascii_art) {
        const asciiEl = document.getElementById('pet-ascii');
        if (asciiEl) asciiEl.textContent = data.ascii_art;
      }

      // 人格卡片高亮
      document.querySelectorAll('.persona-card-style').forEach(card => {
        card.classList.toggle('active', card.dataset.style === data.style);
      });
    });
}

export function adoptPet() {
  const name = prompt('给宠物起个名字:') || '小白';
  fetch('/api/pet/adopt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }).then(r => r.json()).then(data => {
    if (data.ascii_art) {
      document.getElementById('pet-ascii').textContent = data.ascii_art;
    }
    loadPet();
  });
}

export function initPet() {
  document.querySelectorAll('.pet-interact-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      fetch('/api/pet/interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      }).then(r => r.json()).then(() => loadPet());
    });
  });

  // 人格卡片切换
  document.querySelectorAll('.persona-card-style').forEach(card => {
    card.addEventListener('click', () => {
      const style = card.dataset.style;
      fetch('/api/pet/style', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ style }),
      }).then(r => r.json()).then(() => loadPet());
    });
  });

  // 暴露给动态生成的 onclick="adoptPet()" 使用
  window.adoptPet = adoptPet;
}
