
function leafSearch() {
  var query = document.getElementById("query").value;
  if (query == "") return false;
  var gs = document.getElementsByTagName("g");
  for (i = 0; i < gs.length; i++) {
     var list = gs[i].children;
     if (list.length == 2 && list[0].tagName == "circle" && list[1].tagName=="text") {
      var textObject = list[1];
      if (textObject.textContent.match(query)) {
        textObject.style.display = "inline";
        textObject.style.fill = "blue";
      }
    }
  }
  return false;
}

function leafClear() {
  var gs = document.getElementsByTagName("g");
  for (i = 0; i < gs.length; i++) {
    var list = gs[i].children;
    if (list.length == 2 && list[0].tagName == "circle" && list[1].tagName=="text") {
      var textObject = list[1];
      textObject.style.display = "none";
    }
  }
  document.getElementById("query").value = "";
  return false;
}

function leafClick(o) {
  var textObject = o.parentNode.children[1];
  textObject.style.display = "inline";
  textObject.style.fill = "red";
}
