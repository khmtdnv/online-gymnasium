/* Общее поле выбора пользователя; прежняя форма ученика совместима по умолчанию. */
(() => {
  const form = document.querySelector("#student-class-form");
  if (!form) return;
  const picker = document.querySelector("#student-picker");
  const input = document.querySelector("#student-search");
  const results = document.querySelector("#student-results");
  const clear = document.querySelector("#clear-student");
  const studentId = document.getElementById(
    form.dataset.idField || "id_student_id",
  );
  const isTeacher = form.dataset.userKind === "teacher";
  const label = document.querySelector("#student-label");
  const status = document.querySelector("#student-search-status");
  let timer;
  let controller;
  let generation = 0;
  let matches = [];
  let active = -1;

  function close() {
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
    for (const option of results.children)
      option.setAttribute("aria-selected", "false");
  }

  function stopSearch() {
    clearTimeout(timer);
    controller?.abort();
    generation += 1;
    input.setAttribute("aria-busy", "false");
  }

  function updateValidity() {
    input.setCustomValidity(
      studentId.value
        ? ""
        : isTeacher
          ? "Выберите преподавателя из результатов поиска."
          : "Выберите ученика из результатов поиска.",
    );
    clear.hidden = !input.value;
  }

  function resetSelection() {
    studentId.value = "";
    label.value = "";
    matches = [];
    results.replaceChildren();
    close();
    updateValidity();
  }

  function open() {
    if (!matches.length || document.activeElement !== input) return;
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function highlight(index) {
    active = index;
    for (let i = 0; i < results.children.length; i += 1) {
      results.children[i].setAttribute("aria-selected", String(i === active));
    }
    const option = results.children[active];
    input.setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView?.({ block: "nearest" });
  }

  function choose(index) {
    const student = matches[index];
    if (!student) return;
    stopSearch();
    studentId.value = student.id;
    label.value = student.label;
    input.value = student.label;
    close();
    updateValidity();
    status.textContent =
      (isTeacher ? "Выбран преподаватель: " : "Выбран ученик: ") +
      student.label;
    input.focus();
  }

  async function search() {
    stopSearch();
    const current = generation;
    const query = input.value.trim();
    if (query.length < 2) {
      status.textContent = "Введите минимум 2 символа ФИО или email.";
      return;
    }
    controller = new AbortController();
    input.setAttribute("aria-busy", "true");
    status.textContent = isTeacher ? "Ищем преподавателей…" : "Ищем учеников…";
    try {
      const url = new URL(form.dataset.searchUrl, window.location.origin);
      url.searchParams.set("q", query);
      const response = await fetch(url, {
        signal: controller.signal,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok || response.redirected)
        throw new Error("Search unavailable");
      const data = await response.json();
      if (current !== generation) return;
      if (!Array.isArray(data.results))
        throw new Error("Invalid search response");
      matches = data.results;
      results.replaceChildren();
      active = -1;
      input.removeAttribute("aria-activedescendant");
      matches.forEach((student, index) => {
        const option = document.createElement("li");
        option.id = "student-option-" + index;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.dataset.index = String(index);
        option.textContent = student.label;
        results.append(option);
      });
      open();
      status.textContent = matches.length
        ? "Найдено: " +
          matches.length +
          (isTeacher
            ? ". Выберите преподавателя мышью или стрелками и Enter."
            : ". Выберите ученика мышью или стрелками и Enter.") +
          (matches.length === 20 ? " Уточните запрос, если нужного нет." : "")
        : isTeacher
          ? "Преподаватели не найдены. Попробуйте другую часть ФИО или email."
          : "Ученики не найдены. Попробуйте другую часть ФИО или email.";
    } catch (error) {
      if (error.name === "AbortError" || current !== generation) return;
      matches = [];
      results.replaceChildren();
      close();
      status.textContent =
        "Поиск недоступен. Попробуйте ещё раз; при необходимости войдите в админку заново.";
    } finally {
      if (current === generation) input.setAttribute("aria-busy", "false");
    }
  }

  input.addEventListener("input", (event) => {
    stopSearch();
    resetSelection();
    status.textContent = "Введите минимум 2 символа ФИО или email.";
    if (!event.isComposing) timer = setTimeout(search, 300);
  });
  input.addEventListener("compositionend", () => {
    stopSearch();
    timer = setTimeout(search, 300);
  });
  input.addEventListener("focus", () => {
    if (!studentId.value) open();
  });
  input.addEventListener("blur", () => {
    close();
    stopSearch();
  });
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!matches.length) {
        if (!studentId.value) search();
        return;
      }
      open();
      const next =
        event.key === "ArrowDown"
          ? Math.min(active + 1, matches.length - 1)
          : active < 0
            ? matches.length - 1
            : Math.max(active - 1, 0);
      highlight(next);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (!results.hidden && active >= 0) choose(active);
      else if (!studentId.value) search();
    } else if (event.key === "Escape") {
      event.preventDefault();
      stopSearch();
      close();
    } else if (event.key === "Tab") {
      stopSearch();
      close();
    }
  });

  // Сохраняем фокус в поле, чтобы blur не закрыл список раньше клика.
  results.addEventListener("pointerdown", (event) => event.preventDefault());
  results.addEventListener("click", (event) => {
    const option = event.target.closest('[role="option"]');
    if (option && results.contains(option))
      choose(Number(option.dataset.index));
  });
  document.addEventListener("pointerdown", (event) => {
    if (!picker.contains(event.target)) {
      stopSearch();
      close();
    }
  });
  clear.addEventListener("click", () => {
    stopSearch();
    input.value = "";
    resetSelection();
    status.textContent = "Введите минимум 2 символа ФИО или email.";
    input.focus();
  });
  form.addEventListener("submit", (event) => {
    if (!studentId.value) {
      event.preventDefault();
      updateValidity();
      input.focus();
      input.reportValidity();
    }
  });
  updateValidity();
})();
