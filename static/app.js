const serverStatus = document.getElementById("server-status");

fetch("/ping")
  .then((response) => {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  })
  .then((data) => {
    serverStatus.textContent = data.ok
      ? `Servidor conectado. Base de datos: ${data.db}`
      : "El servidor respondió con un estado no válido.";
    console.log(data);
  })
  .catch((error) => {
    serverStatus.textContent = "No se pudo conectar con el backend.";
    console.error(error);
  });
