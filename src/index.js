import style from "./main.scss"
import * as d3 from "d3"

var hid


document.getElementById("btn-see-graph").addEventListener("click", () => {
  hid = document.getElementById("hid").value
  document.getElementById("btn-reload").disabled = false
  reloadRedraw()
})

document.getElementById("btn-reload").addEventListener("click", reloadRedraw)


function reloadRedraw() {
  svg.selectAll("*").remove()
  d3.json(`/graph/${hid}`).then(drawGraph)
  simulation.alphaTarget(0.3).restart()
}


var width = innerWidth,
    height = 250,
    svgDom = document.getElementById("graph"),
    svg = d3.select(svgDom)
      .attr("width", width)
      .attr("height", height),
    simulation = d3.forceSimulation()
      .force("link", d3.forceLink()
                       .id((node) => node.hid)
                       .distance(100))
      .force("charge", d3.forceManyBody())
      .force("center", d3.forceCenter(width / 2, height / 2))


function dragstarted(node){
  if (!d3.event.active) simulation.alphaTarget(0.3).restart()
  node.fx = node.x
  node.fy = node.y
}


function dragged(node){
  node.fx = d3.event.x
  node.fy = d3.event.y
}


function dragended(node){
  if (!d3.event.active) simulation.alphaTarget(0)
  node.fx = null
  node.fy = null
}


function drawGraph(graph){
  var count = 0,
      parents = graph.edges.map((edge) => edge.parent)
                           .filter((edge) => edge)

  graph.edges.forEach((edge) => {
    if(edge.parent === null) {
      edge.source = `empty-before-${count++}`
      graph.nodes.push({hid: edge.source, empty: true, x:-300, y: 0})
    } else {
      edge.source = edge.parent
    }
    edge.target = edge.hist
  })

  graph.nodes.forEach((node) => node.leaf = !parents.includes(node.hid))

  svg.append("defs")
    .attr("class", "markers")
    .selectAll("marker")
      .data(["insert", "update"])
      .enter().append("marker")
        .attr("id", (d) => d)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 20)
        .attr("refY", -1.5)
        .attr("markerWidth", 5)
        .attr("markerHeight", 5)
        .attr("orient", "auto")
        .append("path")
          .attr("d", "M0,-5L10,0L0,5")

  var path = svg.append("g")
    .attr("class", "edges")
    .selectAll("path")
      .data(graph.edges)
      .enter().append("path")
        .attr("class", (d) => " edge " + d.reason)
        .attr("marker-end", (d) => `url(#${d.reason})`)

  var node = svg.append("g")
    .attr("class", "nodes")
    .selectAll("circle")
      .data(graph.nodes)
      .enter().append("circle")
        .attr("r", 8)
        .attr("class",
          (d) => (d.empty ? "empty" : (d.leaf ? "leaf" : "not-leaf"))
        )
        .call(d3.drag().on("start", dragstarted)
                       .on("drag", dragged)
                       .on("end", dragended))

  var text = svg.append("g")
    .attr("class", "nodes-text")
    .selectAll("text")
      .data(graph.nodes)
      .enter().append("text")
        .text((d) => d.pid === undefined ? "" :
                     `[${d.pid || "<NULL>"}] ${d.title || ""}`)

  simulation.nodes(graph.nodes).on("tick", () => {
    path.attr("d", (d) => {
      let dx = d.target.x - d.source.x,
          dy = d.target.y - d.source.y,
          dr = Math.sqrt(dx * dx + dy * dy)
      return `M${d.source.x},${d.source.y}` +
             `A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`
    })
    node.attr("cx", (d) => d.x)
        .attr("cy", (d) => d.y)
    text.attr("x", (d) => d.x + 5)
        .attr("y", (d) => d.y - 10)
  })
  simulation.force("link").links(graph.edges)
}
