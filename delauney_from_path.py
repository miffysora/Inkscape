#!/usr/bin/env python
# coding: UTF-8
# standard library
import sys
import os
# local library
import inkex
import simplestyle
import simplepath
import simpletransform
import voronoi
import cubicsuperpath
from PIL import Image
inkex.localize()


class Point:
	def __init__(self, x, y):
		self.x = x
		self.y = y
	def __lt__(self,other):
		return (self.x*self.y<other.x*other.y)
	def __le__(self,other):
		return (self.x*self.y<=other.y*other.y)
	def __gt__(self,other):
		return (self.x*self.y>other.x*other.y)
	def __ge__(self,other):
		return (self.x*self.y>=other.x*other.y)
	def __eq__(self,other):
		return (self.x==other.x) and (self.y==other.y)
	def __ne__(self,other):
		return (self.x!=other.x) or (self.y!=other.y)

	def __str__(self):
		return "("+str(self.x)+","+str(self.y)+")"


class Voronoi2svg(inkex.Effect):
	def __init__(self):
		inkex.Effect.__init__(self)

		# {{{ Additional options

		self.OptionParser.add_option(
			"--tab",
			action="store",
			type="string",
			dest="tab")

		#}}}

	# {{{ Clipping a line by a bounding box
	def dot(self, x, y):
		return x[0] * y[0] + x[1] * y[1]

	def intersectLineSegment(self, line, v1, v2):
		s1 = self.dot(line, v1) - line[2]
		s2 = self.dot(line, v2) - line[2]
		if s1 * s2 > 0:
			return (0, 0, False)
		else:
			tmp = self.dot(line, v1) - self.dot(line, v2)
			if tmp == 0:
				return (0, 0, False)
			u = (line[2] - self.dot(line, v2)) / tmp
			v = 1 - u
			return (u * v1[0] + v * v2[0], u * v1[1] + v * v2[1], True)

	def clipEdge(self, vertices, lines, edge, bbox):
		#bounding box corners
		bbc = []
		bbc.append((bbox[0], bbox[2]))
		bbc.append((bbox[1], bbox[2]))
		bbc.append((bbox[1], bbox[3]))
		bbc.append((bbox[0], bbox[3]))

		#record intersections of the line with bounding box edges
		line = (lines[edge[0]])
		interpoints = []
		for i in range(4):
			p = self.intersectLineSegment(line, bbc[i], bbc[(i + 1) % 4])
			if (p[2]):
				interpoints.append(p)

		#if the edge has no intersection, return empty intersection
		if (len(interpoints) < 2):
			return []

		if (len(interpoints) > 2):  #happens when the edge crosses the corner of the box
			interpoints = list(set(interpoints))  #remove doubles

		#points of the edge
		v1 = vertices[edge[1]]
		interpoints.append((v1[0], v1[1], False))
		v2 = vertices[edge[2]]
		interpoints.append((v2[0], v2[1], False))

		#sorting the points in the widest range to get them in order on the line
		minx = interpoints[0][0]
		maxx = interpoints[0][0]
		miny = interpoints[0][1]
		maxy = interpoints[0][1]
		for point in interpoints:
			minx = min(point[0], minx)
			maxx = max(point[0], maxx)
			miny = min(point[1], miny)
			maxy = max(point[1], maxy)

		if (maxx - minx) > (maxy - miny):
			interpoints.sort()
		else:
			interpoints.sort(key=lambda pt: pt[1])

		start = []
		inside = False  #true when the part of the line studied is in the clip box
		startWrite = False  #true when the part of the line is in the edge segment
		for point in interpoints:
			if point[2]:  #The point is a bounding box intersection
				if inside:
					if startWrite:
						return [[start[0], start[1]], [point[0], point[1]]]
					else:
						return []
				else:
					if startWrite:
						start = point
				inside = not inside
			else:  #The point is a segment endpoint
				if startWrite:
					if inside:
						#a vertex ends the line inside the bounding box
						return [[start[0], start[1]], [point[0], point[1]]]
					else:
						return []
				else:
					if inside:
						start = point
				startWrite = not startWrite

	#}}}

	#{{{ Transformation helpers

	def invertTransform(self, mat):
		det = mat[0][0] * mat[1][1] - mat[0][1] * mat[1][0]
		if det != 0:  #det is 0 only in case of 0 scaling
			#invert the rotation/scaling part
			a11 = mat[1][1] / det
			a12 = -mat[0][1] / det
			a21 = -mat[1][0] / det
			a22 = mat[0][0] / det

			#invert the translational part
			a13 = -(a11 * mat[0][2] + a12 * mat[1][2])
			a23 = -(a21 * mat[0][2] + a22 * mat[1][2])

			return [[a11, a12, a13], [a21, a22, a23]]
		else:
			return [[0, 0, -mat[0][2]], [0, 0, -mat[1][2]]]

	def getGlobalTransform(self, node):
		parent = node.getparent()
		myTrans = simpletransform.parseTransform(node.get('transform'))
		if myTrans:
			if parent is not None:
				parentTrans = self.getGlobalTransform(parent)
				if parentTrans:
					return simpletransform.composeTransform(parentTrans, myTrans)
				else:
					return myTrans
		else:
			if parent is not None:
				return self.getGlobalTransform(parent)
			else:
				return None


	#}}}

	def effect(self):

		#{{{ Check that elements have been selected

		if len(self.options.ids) == 0:
			inkex.errormsg(_("Please select objects!"))
			return

		#}}}

		#{{{ Drawing styles

		linestyle = {
			'stroke': '#000000',
			'stroke-width': str(self.unittouu('1px')),
			'fill': 'none'
		}

		facestyle = {
			'stroke': '#000000',
			'stroke-width':'0px',# str(self.unittouu('1px')),
			'fill': 'none'
		}

		#}}}

		#{{{ Handle the transformation of the current group
		parentGroup = self.getParentNode(self.selected[self.options.ids[0]])

		svg = self.document.getroot()
		children =svg.getchildren()
		fp=open("log.txt","w")
		img=None
		width_in_svg=1
		height_in_svg=1
		for child in children:
			if child.tag=="{http://www.w3.org/2000/svg}g":
				ccc=child.getchildren()
				for c in ccc:
					if c.tag=="{http://www.w3.org/2000/svg}image":
						href=c.attrib["{http://www.w3.org/1999/xlink}href"]
						fp.write(href)
						img = Image.open(href)
						width_in_svg=child.attrib['width']
						height_in_svg=child.attrib['height']
			elif child.tag=="{http://www.w3.org/2000/svg}image":
				href=child.attrib["{http://www.w3.org/1999/xlink}href"]
				width_in_svg=child.attrib['width']
				height_in_svg=child.attrib['height']
				if "file://" in href:
					href=href[7:]
				fp.write(href+"\n")
				img = Image.open(href).convert("RGB")
		width=-1
		height=-1
		if img!=None:
			imagesize = img.size
			width=img.size[0]
			height=img.size[1]
		fp.write("imageSize="+str(imagesize))



		trans = self.getGlobalTransform(parentGroup)
		invtrans = None
		if trans:
			invtrans = self.invertTransform(trans)

		#}}}

		#{{{ Recovery of the selected objects

		pts = []
		nodes = []
		seeds = []

		fp.write('num:'+str(len(self.options.ids))+'\n')
		for id in self.options.ids:
			node = self.selected[id]
			nodes.append(node)
			if(node.tag=="{http://www.w3.org/2000/svg}path"):#pathだった場合
				#パスの頂点座標を取得
				points = cubicsuperpath.parsePath(node.get('d'))
				fp.write(str(points)+"\n")
				for p in points[0]:
					pt=[p[1][0],p[1][1]]
					if trans:
						simpletransform.applyTransformToPoint(trans, pt)
					pts.append(Point(pt[0], pt[1]))
					seeds.append(Point(p[1][0], p[1][1]))
			else:#その他の図形の場合
				bbox = simpletransform.computeBBox([node])
				if bbox:
					cx = 0.5 * (bbox[0] + bbox[1])
					cy = 0.5 * (bbox[2] + bbox[3])
					pt = [cx, cy]
					if trans:
						simpletransform.applyTransformToPoint(trans, pt)
					pts.append(Point(pt[0], pt[1]))
					seeds.append(Point(cx, cy))
		pts.sort()
		seeds.sort()
		fp.write("*******sorted!***********"+str(len(seeds))+"\n")

		#}}}

		#{{{ Creation of groups to store the result
		# Delaunay
		groupDelaunay = inkex.etree.SubElement(parentGroup, inkex.addNS('g', 'svg'))
		groupDelaunay.set(inkex.addNS('label', 'inkscape'), 'Delaunay')

		#}}}

		scale_x=float(width_in_svg)/float(width)
		scale_y=float(height_in_svg)/float(height)
		fp.write('width='+str(width)+', height='+str(height)+'\n')
		fp.write('scale_x='+str(scale_x)+', scale_y='+str(scale_y)+'\n')

		#{{{ Voronoi diagram generation

		triangles = voronoi.computeDelaunayTriangulation(seeds)
		for triangle in triangles:
			p1 = seeds[triangle[0]]
			p2 = seeds[triangle[1]]
			p3 = seeds[triangle[2]]
			cmds = [['M', [p1.x, p1.y]],
					['L', [p2.x, p2.y]],
					['L', [p3.x, p3.y]],
					['Z', []]]
			path = inkex.etree.Element(inkex.addNS('path', 'svg'))
			path.set('d', simplepath.formatPath(cmds))
			middleX=(p1.x+p2.x+p3.x)/3.0/scale_x
			middleY=(p1.y+p2.y+p3.y)/3.0/scale_y
			fp.write("x:"+str(middleX)+" y:"+str(middleY)+"\n")
			if img!=None and imagesize[0]>middleX and imagesize[1]>middleY and middleX>=0 and middleY>=0:
				r,g,b = img.getpixel((middleX,middleY))
				facestyle["fill"]=simplestyle.formatColor3i(r,g,b)
			else:
				facestyle["fill"]="black"
			path.set('style', simplestyle.formatStyle(facestyle))
			groupDelaunay.append(path)
		fp.close()
				#}}}


if __name__ == "__main__":
	e = Voronoi2svg()
	e.affect()


# vim: expandtab shiftwidth=2 tabstop=2 softtabstop=2 fileencoding=utf-8 textwidth=99
