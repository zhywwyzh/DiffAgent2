/* 本地阅读交互，不读取配置、连接后端或执行控制命令。 */
(() => {
  const sidebar = document.querySelector('#sidebar');
  const menu = document.querySelector('#menu');
  const search = document.querySelector('#search');
  const status = document.querySelector('#search-status');
  const sections = [...document.querySelectorAll('[data-searchable]')];
  const links = [...document.querySelectorAll('nav a')];
  const groups = [...document.querySelectorAll('.nav-group')];
  const dividers = [...document.querySelectorAll('.group-divider')];
  let openBeforeSearch = null;
  const texts = new Map(sections.map(section => [section, section.textContent.toLocaleLowerCase()]));
  function revealNavigation(target) {
    const section = target.closest('[data-searchable]') || target;
    const link = links.find(link => link.hash === '#' + section.id);
    const group = link?.closest('.nav-group');
    if (group) group.open = true;
  }
  function filter() {
    const terms = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    if (terms.length && !openBeforeSearch) {
      openBeforeSearch = new Map(groups.map(group => [group, group.open]));
    }
    let matches = 0;
    sections.forEach(section => {
      const visible = terms.every(term => texts.get(section).includes(term));
      section.hidden = !visible;
      if (visible) matches++;
    });
    links.forEach(link => {
      const target = document.getElementById(link.hash.slice(1));
      link.hidden = Boolean(target?.hidden);
    });
    groups.forEach(group => {
      group.hidden = [...group.querySelectorAll('a')].every(link => link.hidden);
      if (terms.length && !group.hidden) group.open = true;
      else if (!terms.length && openBeforeSearch) group.open = openBeforeSearch.get(group);
    });
    dividers.forEach(divider => {
      divider.hidden = divider.dataset.sectionIds.split(' ').every(id => document.getElementById(id)?.hidden);
    });
    if (!terms.length) openBeforeSearch = null;
    status.textContent = terms.length ? (matches ? `找到 ${matches} 个相关章节` : '未找到匹配内容，请换一个关键词。') : '';
    progress();
  }
  function revealHash() {
    if (!location.hash) return;
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!target) return;
    if (target.hidden || target.closest('[data-searchable]')?.hidden) {
      search.value = '';
      filter();
    }
    revealNavigation(target);
    if (target.dataset.sectionIds) {
      revealNavigation(document.getElementById(target.dataset.sectionIds.split(' ')[0]));
    }
    requestAnimationFrame(() => target.scrollIntoView({block:'start'}));
  }
  menu.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    menu.setAttribute('aria-expanded', String(open));
  });
  links.forEach(link => link.addEventListener('click', () => {
    sidebar.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false');
  }));
  search.addEventListener('input', filter);
  document.querySelector('#print').addEventListener('click', () => window.print());
  document.querySelector('#top').addEventListener('click', () => window.scrollTo({top:0,behavior:'smooth'}));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      sidebar.classList.remove('open');
      menu.setAttribute('aria-expanded', 'false');
      search.value = ''; filter();
    }
    if (event.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) {
      event.preventDefault(); sidebar.classList.add('open');
      menu.setAttribute('aria-expanded','true'); search.focus();
    }
  });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        links.forEach(link => {
          const active = link.hash === '#' + entry.target.id;
          link.classList.toggle('active', active);
          if (active) link.setAttribute('aria-current','location');
          else link.removeAttribute('aria-current');
        });
        revealNavigation(entry.target);
      });
    }, {rootMargin:'-90px 0px -65% 0px',threshold:0});
    sections.forEach(section => observer.observe(section));
  }
  function progress() {
    const available = document.documentElement.scrollHeight - innerHeight;
    document.querySelector('.reading-progress').style.width = `${available > 0 ? scrollY / available * 100 : 0}%`;
  }
  window.addEventListener('scroll', progress, {passive:true});
  window.addEventListener('hashchange', revealHash);
  revealHash(); progress();
})();
