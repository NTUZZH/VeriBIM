"""Small synthetic IFC models for the repair tests, written entity by entity so
the same builder works for IFC2X3, IFC4 and IFC4X3. Lengths in millimetres, so
every test also exercises the unit conversion."""
from __future__ import annotations

import ifcopenshell
import ifcopenshell.guid

MM = 1000.0


class Builder:
    def __init__(self, schema: str):
        self.schema = schema
        f = self.f = ifcopenshell.file(schema=schema)
        person = f.create_entity("IfcPerson", FamilyName="Test")
        org = f.create_entity("IfcOrganization", Name="Test")
        pao = f.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=org)
        app = f.create_entity("IfcApplication", ApplicationDeveloper=org, Version="1",
                              ApplicationFullName="synth", ApplicationIdentifier="synth")
        self.history = f.create_entity("IfcOwnerHistory", OwningUser=pao, OwningApplication=app,
                                       ChangeAction="ADDED", CreationDate=0)
        unit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
        units = f.create_entity("IfcUnitAssignment", Units=[unit])
        self.context = f.create_entity(
            "IfcGeometricRepresentationContext", ContextType="Model", CoordinateSpaceDimension=3,
            Precision=1e-5, WorldCoordinateSystem=self.axis((0, 0, 0)))
        self.body = f.create_entity(
            "IfcGeometricRepresentationSubContext", ContextIdentifier="Body", ContextType="Model",
            ParentContext=self.context, TargetView="MODEL_VIEW")
        self.project = self.root("IfcProject", Name="P", UnitsInContext=units,
                                 RepresentationContexts=[self.context])
        self.site = self.root("IfcSite", Name="S", ObjectPlacement=self.placement(None, (0, 0, 0)))
        self.building = self.root("IfcBuilding", Name="B",
                                  ObjectPlacement=self.placement(self.site.ObjectPlacement, (0, 0, 0)))
        self.storey = self.root("IfcBuildingStorey", Name="L1",
                                ObjectPlacement=self.placement(self.building.ObjectPlacement, (0, 0, 0)))
        self.root("IfcRelAggregates", RelatingObject=self.project, RelatedObjects=[self.site])
        self.root("IfcRelAggregates", RelatingObject=self.site, RelatedObjects=[self.building])
        self.root("IfcRelAggregates", RelatingObject=self.building, RelatedObjects=[self.storey])
        self.contained = []

    # -------------------------------------------------------------- basics
    def root(self, cls, **kw):
        return self.f.create_entity(cls, GlobalId=ifcopenshell.guid.new(),
                                    OwnerHistory=self.history, **kw)

    def point(self, xyz):
        return self.f.create_entity("IfcCartesianPoint", Coordinates=tuple(float(v) for v in xyz))

    def direction(self, xyz):
        return self.f.create_entity("IfcDirection", DirectionRatios=tuple(float(v) for v in xyz))

    def axis(self, loc, z=None, x=None):
        return self.f.create_entity("IfcAxis2Placement3D", Location=self.point(loc),
                                    Axis=self.direction(z) if z else None,
                                    RefDirection=self.direction(x) if x else None)

    def placement(self, parent, loc, z=None, x=None):
        return self.f.create_entity("IfcLocalPlacement", PlacementRelTo=parent,
                                    RelativePlacement=self.axis(loc, z, x))

    def rect_solid(self, xdim, ydim, depth, profile_centre, position=None, direction=(0, 0, 1)):
        profile = self.f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA",
            Position=self.f.create_entity("IfcAxis2Placement2D", Location=self.f.create_entity(
                "IfcCartesianPoint", Coordinates=tuple(float(v) for v in profile_centre))),
            XDim=float(xdim), YDim=float(ydim))
        return self.f.create_entity("IfcExtrudedAreaSolid", SweptArea=profile,
                                    Position=position or self.axis((0, 0, 0)),
                                    ExtrudedDirection=self.direction(direction), Depth=float(depth))

    def shape(self, solid):
        rep = self.f.create_entity("IfcShapeRepresentation", ContextOfItems=self.body,
                                   RepresentationIdentifier="Body", RepresentationType="SweptSolid",
                                   Items=[solid])
        return self.f.create_entity("IfcProductDefinitionShape", Representations=[rep])

    def contain(self, product):
        self.contained.append(product)

    def finish(self):
        if self.contained:
            self.root("IfcRelContainedInSpatialStructure", RelatingStructure=self.storey,
                      RelatedElements=self.contained)
        return self.f

    # -------------------------------------------------------------- elements
    def wall(self, origin, length, thickness, height=3000.0, x_dir=None, name="W"):
        cls = "IfcWallStandardCase" if self.schema in ("IFC2X3", "IFC4") else "IfcWall"
        wall = self.root(cls, Name=name, ObjectPlacement=self.placement(
            self.storey.ObjectPlacement, origin, (0, 0, 1) if x_dir else None, x_dir))
        wall.Representation = self.shape(self.rect_solid(length, thickness, height, (length / 2, 0)))
        self.contain(wall)
        return wall

    def door_extruded_across(self, wall, along, wall_thickness, width, height, leaf_depth,
                             flipped=False):
        """An opening drawn the way the benchmark's Revit-exported doors are:
        profile = face (XDim height along wall z, YDim width along wall x),
        extruded across the wall by the wall's thickness; the door hangs from
        the opening and is a slab centred in the wall."""
        if not flipped:
            opening_loc = (along, -wall_thickness / 2, 0)
            position = self.axis((0, 0, 0), (0, 1, 0), (0, 0, 1))
            door_axis = (None, None)
        else:
            # extruded towards -y from the far face, profile y running along -x,
            # door turned half a turn about z (as in DOR-UPD-TOP-G7arc-004)
            opening_loc = (along + width, wall_thickness / 2, 0)
            position = self.axis((0, 0, 0), (0, -1, 0), (0, 0, 1))
            door_axis = ((0, 0, 1), (-1, 0, 0))
        opening = self.root("IfcOpeningElement", Name="Opening",
                            ObjectPlacement=self.placement(wall.ObjectPlacement, opening_loc))
        solid = self.rect_solid(height, width, wall_thickness, (height / 2, width / 2), position)
        opening.Representation = self.shape(solid)
        self.root("IfcRelVoidsElement", RelatingBuildingElement=wall, RelatedOpeningElement=opening)
        door = self.root("IfcDoor", Name="D", ObjectPlacement=self.placement(
            opening.ObjectPlacement, (0, 0, 0), *door_axis), OverallHeight=height, OverallWidth=width)
        # leaf body: width x leaf_depth x height, centred in the wall
        door.Representation = self.shape(self.rect_solid(
            width, leaf_depth, height, (width / 2, wall_thickness / 2)))
        self.root("IfcRelFillsElement", RelatingOpeningElement=opening, RelatedBuildingElement=door)
        self.contain(door)
        return opening, door


def two_walls(schema):
    """Wall A along x (100 mm), wall B turned 90 degrees (200 mm), door in A."""
    b = Builder(schema)
    wall_a = b.wall((0, 0, 0), 5000, 100, name="A")
    wall_b = b.wall((6000, 0, 0), 5000, 200, x_dir=(0, 1, 0), name="B")
    return b, wall_a, wall_b
