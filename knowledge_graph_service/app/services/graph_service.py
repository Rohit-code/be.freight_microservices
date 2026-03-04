"""
Knowledge Graph Service
Manages relationships between carriers, lanes, routes, ports, and validity periods
Uses ArangoDB for graph storage
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)

# Import ArangoDB client with error handling
try:
    from arango import ArangoClient
    from arango.database import StandardDatabase
    ARANGO_AVAILABLE = True
except ImportError:
    ARANGO_AVAILABLE = False
    logger.warning("python-arango not installed. Install with: pip install python-arango")
    logger.warning("Knowledge Graph Service will not function without python-arango")


class GraphService:
    """
    ArangoDB Graph Service for rate sheet relationships.
    
    IMPORTANT - Node vs Edge Responsibility:
    =========================================
    
    Nodes store METADATA only:
        - RateSheet: organization_id, carrier_name, valid_from, valid_to, created_at
        - Port: code, name, country, city
        - Lane: origin, destination, container_type
        - Carrier: name
    
    Edges store RATE FACTS (pricing data):
        - HAS_ROUTE: base_rate, transit_time, container_type, valid_from, valid_to, rate_sheet_id
        - HAS_CARRIER: (relationship only, no rate data)
        - CONNECTS_TO: (relationship only, no rate data)
    
    Rule: Rates ALWAYS live on edges, NEVER on nodes.
    
    Why this matters:
        - Prevents graph bloat (node data stays small)
        - Enables efficient traversal (filter by edge properties)
        - Validity-aware queries filter on edge properties
        - Multiple rate sheets can share Port/Lane nodes without data conflicts
    
    Example query pattern:
        FOR route IN HAS_ROUTE
            FILTER route.valid_from <= @date AND route.valid_to >= @date
            FILTER route.base_rate <= @max_price
            RETURN route
    """
    
    def __init__(self):
        self.client = None
        self.db: Optional[StandardDatabase] = None
        self.host = settings.ARANGO_HOST
        self.user = settings.ARANGO_USER
        self.password = settings.ARANGO_PASSWORD
        self.database_name = settings.ARANGO_DATABASE
    
    async def initialize(self):
        """Initialize ArangoDB connection"""
        if not ARANGO_AVAILABLE:
            raise ImportError(
                "python-arango is not installed. "
                "Install it with: pip install python-arango"
            )
        
        import asyncio
        try:
            # Run synchronous ArangoDB operations in executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._initialize_sync)
            logger.info("✅ ArangoDB connection established")
        except Exception as e:
            logger.error(f"Failed to connect to ArangoDB: {e}")
            raise
    
    def _initialize_sync(self):
        """Synchronous initialization (runs in executor)"""
        # Create ArangoDB client
        self.client = ArangoClient(hosts=self.host)
        
        # Connect to _system database to create/access our database
        sys_db = self.client.db('_system', username=self.user, password=self.password)
        
        # Create database if it doesn't exist
        if not sys_db.has_database(self.database_name):
            sys_db.create_database(self.database_name)
            logger.info(f"Created database: {self.database_name}")
        
        # Connect to our database
        self.db = self.client.db(self.database_name, username=self.user, password=self.password)
        
        # Create collections (vertex and edge collections)
        self._ensure_collections()
    
    def _ensure_collections(self):
        """Ensure all required collections exist"""
        # Vertex collections
        vertex_collections = ['RateSheet', 'Carrier', 'Port', 'Lane']
        for coll_name in vertex_collections:
            if not self.db.has_collection(coll_name):
                self.db.create_collection(coll_name)
                logger.info(f"Created vertex collection: {coll_name}")
        
        # Edge collections
        edge_collections = ['HAS_CARRIER', 'HAS_ROUTE', 'CONNECTS_TO']
        for coll_name in edge_collections:
            if not self.db.has_collection(coll_name):
                self.db.create_collection(coll_name, edge=True)
                logger.info(f"Created edge collection: {coll_name}")
    
    async def close(self):
        """Close ArangoDB connection"""
        # ArangoDB client doesn't need explicit closing, but we can clear references
        self.db = None
        self.client = None
    
    async def create_rate_sheet_graph(
        self,
        rate_sheet_id: str,
        organization_id: int,
        carrier_name: str,
        routes: List[Dict[str, Any]],
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None
    ):
        """
        Create graph nodes and relationships for a rate sheet
        
        Structure:
        - RateSheet vertex (id, organization_id, carrier_name, valid_from, valid_to)
        - Carrier vertex (name)
        - Port vertices (origin_port, destination_port)
        - Lane vertex (connects origin_port -> destination_port)
        - Route edge (connects RateSheet -> Lane)
        - Carrier edge (connects RateSheet -> Carrier)
        """
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._create_rate_sheet_graph_sync,
            rate_sheet_id, organization_id, carrier_name, routes, valid_from, valid_to
        )
    
    def _sanitize_key(self, value: str) -> str:
        """Sanitize a string to be a valid ArangoDB document key.
        Only allows: a-z, A-Z, 0-9, _, -, :, ., @
        """
        import re
        # Replace spaces with underscores, then remove all invalid characters
        sanitized = value.replace(' ', '_').replace("'", "").replace('"', '')
        sanitized = re.sub(r'[^a-zA-Z0-9_\-:\.@]', '', sanitized)
        return sanitized.upper() if sanitized else 'UNKNOWN'
    
    def _create_rate_sheet_graph_sync(
        self,
        rate_sheet_id: str,
        organization_id: int,
        carrier_name: str,
        routes: List[Dict[str, Any]],
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None
    ):
        """Synchronous implementation"""
        try:
            # Create or update RateSheet vertex
            rate_sheet_key = f"rs_{rate_sheet_id}"
            rate_sheet_doc = {
                "_key": rate_sheet_key,
                "id": rate_sheet_id,
                "organization_id": organization_id,
                "carrier_name": carrier_name,
                "valid_from": valid_from.isoformat() if valid_from else None,
                "valid_to": valid_to.isoformat() if valid_to else None,
                "created_at": datetime.utcnow().isoformat()
            }
            self.db.collection('RateSheet').insert(rate_sheet_doc, overwrite=True)
            
            # Create or update Carrier vertex and edge
            carrier_key = f"carrier_{self._sanitize_key(carrier_name)}"
            carrier_doc = {
                "_key": carrier_key,
                "name": carrier_name
            }
            self.db.collection('Carrier').insert(carrier_doc, overwrite=True)
            
            # Create HAS_CARRIER edge
            self.db.collection('HAS_CARRIER').insert({
                "_from": f"RateSheet/{rate_sheet_key}",
                "_to": f"Carrier/{carrier_key}"
            }, overwrite=True)
            
            # Create Port vertices, Lane vertices, and Route edges
            for route in routes:
                origin = route.get("origin_port")
                destination = route.get("destination_port")
                container_type = route.get("container_type")
                
                if origin and destination:
                    # Create origin port vertex
                    origin_key = f"port_{self._sanitize_key(origin)}"
                    origin_doc = {
                        "_key": origin_key,
                        "code": origin,
                        "name": origin
                    }
                    self.db.collection('Port').insert(origin_doc, overwrite=True)
                    
                    # Create destination port vertex
                    dest_key = f"port_{self._sanitize_key(destination)}"
                    dest_doc = {
                        "_key": dest_key,
                        "code": destination,
                        "name": destination
                    }
                    self.db.collection('Port').insert(dest_doc, overwrite=True)
                    
                    # Create Lane vertex
                    container_key = self._sanitize_key(container_type) if container_type else 'ANY'
                    lane_key = f"lane_{origin_key}_{dest_key}_{container_key}"
                    lane_doc = {
                        "_key": lane_key,
                        "origin": origin,
                        "destination": destination,
                        "container_type": container_type
                    }
                    self.db.collection('Lane').insert(lane_doc, overwrite=True)
                    
                    # Create CONNECTS_TO edges
                    self.db.collection('CONNECTS_TO').insert({
                        "_from": f"Port/{origin_key}",
                        "_to": f"Lane/{lane_key}"
                    }, overwrite=True)
                    
                    self.db.collection('CONNECTS_TO').insert({
                        "_from": f"Lane/{lane_key}",
                        "_to": f"Port/{dest_key}"
                    }, overwrite=True)
                    
                    # Create HAS_ROUTE edge from RateSheet to Lane
                    # Include validity dates for time-aware route traversal
                    route_edge_key = f"route_{rate_sheet_key}_{lane_key}"
                    self.db.collection('HAS_ROUTE').insert({
                        "_key": route_edge_key,
                        "_from": f"RateSheet/{rate_sheet_key}",
                        "_to": f"Lane/{lane_key}",
                        "container_type": container_type,
                        "base_rate": route.get("base_rate"),
                        "transit_time": route.get("transit_time"),
                        # Validity properties for time-aware queries
                        "valid_from": valid_from.isoformat() if valid_from else None,
                        "valid_to": valid_to.isoformat() if valid_to else None,
                        "rate_sheet_id": rate_sheet_id
                    }, overwrite=True)
            
            logger.info(f"Created graph for rate sheet {rate_sheet_id}")
            
        except Exception as e:
            logger.error(f"Error creating graph for rate sheet {rate_sheet_id}: {e}")
            raise
    
    async def find_routes_by_lane(
        self,
        organization_id: int,
        origin_port: str,
        destination_port: str,
        container_type: Optional[str] = None,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Find all rate sheets that have routes matching the lane
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._find_routes_by_lane_sync,
            organization_id, origin_port, destination_port, container_type, valid_date
        )
    
    def _find_routes_by_lane_sync(
        self,
        organization_id: int,
        origin_port: str,
        destination_port: str,
        container_type: Optional[str] = None,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Synchronous implementation"""
        try:
            # Build AQL query
            valid_date_str = valid_date.isoformat() if valid_date else None
            
            aql = """
            FOR origin IN Port
                FILTER origin.code == @origin
            FOR dest IN Port
                FILTER dest.code == @destination
            FOR lane IN Lane
                FILTER lane.origin == @origin AND lane.destination == @destination
                FILTER @container_type == null OR lane.container_type == @container_type
            FOR route_edge IN HAS_ROUTE
                FILTER route_edge._to == lane._id
            FOR rs IN RateSheet
                FILTER rs._id == route_edge._from
                    AND rs.organization_id == @org_id
                    AND (@valid_date == null OR 
                         (rs.valid_from == null OR rs.valid_from <= @valid_date) AND
                         (rs.valid_to == null OR rs.valid_to >= @valid_date))
            SORT route_edge.base_rate ASC
            LIMIT 50
            RETURN {
                rate_sheet_id: rs.id,
                carrier_name: rs.carrier_name,
                container_type: route_edge.container_type,
                base_rate: route_edge.base_rate,
                transit_time: route_edge.transit_time,
                valid_from: rs.valid_from,
                valid_to: rs.valid_to
            }
            """
            
            cursor = self.db.aql.execute(aql, bind_vars={
                "origin": origin_port,
                "destination": destination_port,
                "org_id": organization_id,
                "container_type": container_type,
                "valid_date": valid_date_str
            })
            
            routes = [doc for doc in cursor]
            return routes
            
        except Exception as e:
            logger.error(f"Error finding routes by lane: {e}")
            return []
    
    async def find_carrier_routes(
        self,
        organization_id: int,
        carrier_name: str,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Find all routes for a specific carrier"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._find_carrier_routes_sync,
            organization_id, carrier_name, valid_date
        )
    
    def _find_carrier_routes_sync(
        self,
        organization_id: int,
        carrier_name: str,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Synchronous implementation"""
        try:
            valid_date_str = valid_date.isoformat() if valid_date else None
            
            aql = """
            FOR rs IN RateSheet
                FILTER rs.organization_id == @org_id
                FILTER (@valid_date == null OR 
                        (rs.valid_from == null OR rs.valid_from <= @valid_date) AND
                        (rs.valid_to == null OR rs.valid_to >= @valid_date))
            FOR carrier_edge IN HAS_CARRIER
                FILTER carrier_edge._from == rs._id
            FOR carrier IN Carrier
                FILTER carrier._id == carrier_edge._to AND carrier.name == @carrier
            FOR route_edge IN HAS_ROUTE
                FILTER route_edge._from == rs._id
            FOR lane IN Lane
                FILTER lane._id == route_edge._to
            SORT route_edge.base_rate ASC
            RETURN {
                rate_sheet_id: rs.id,
                origin_port: lane.origin,
                destination_port: lane.destination,
                container_type: route_edge.container_type,
                base_rate: route_edge.base_rate,
                transit_time: route_edge.transit_time
            }
            """
            
            cursor = self.db.aql.execute(aql, bind_vars={
                "org_id": organization_id,
                "carrier": carrier_name,
                "valid_date": valid_date_str
            })
            
            routes = [doc for doc in cursor]
            return routes
            
        except Exception as e:
            logger.error(f"Error finding carrier routes: {e}")
            return []
    
    async def find_alternative_routes(
        self,
        organization_id: int,
        origin_port: str,
        destination_port: str,
        max_hops: int = 2,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Find alternative routes via intermediate ports (transshipment)
        Optionally filters by validity date.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._find_alternative_routes_sync,
            organization_id, origin_port, destination_port, max_hops, valid_date
        )
    
    def _find_alternative_routes_sync(
        self,
        organization_id: int,
        origin_port: str,
        destination_port: str,
        max_hops: int = 2,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Synchronous implementation with validity filtering"""
        try:
            # Build validity filter clause
            validity_filter = ""
            if valid_date:
                validity_filter = """
                    AND (route1.valid_from == null OR route1.valid_from <= @valid_date)
                    AND (route1.valid_to == null OR route1.valid_to >= @valid_date)
                    AND (route2.valid_from == null OR route2.valid_from <= @valid_date)
                    AND (route2.valid_to == null OR route2.valid_to >= @valid_date)
                """
            
            # Simplified AQL query for alternative routes
            # Find routes via intermediate ports using graph traversal
            # Now includes validity filtering on HAS_ROUTE edges
            aql = f"""
            FOR origin IN Port
                FILTER origin.code == @origin
            FOR lane1 IN Lane
                FILTER lane1.origin == @origin
            FOR route1 IN HAS_ROUTE
                FILTER route1._to == lane1._id
            FOR rs IN RateSheet
                FILTER rs._id == route1._from AND rs.organization_id == @org_id
            FOR lane2 IN Lane
                FILTER lane2.destination == @destination
                AND lane2.origin == lane1.destination
            FOR route2 IN HAS_ROUTE
                FILTER route2._to == lane2._id
                {validity_filter}
            FOR rs2 IN RateSheet
                FILTER rs2._id == route2._from AND rs2.organization_id == @org_id
            RETURN {{
                origin_port: lane1.origin,
                intermediate_port: lane1.destination,
                destination_port: lane2.destination,
                hop_count: 2,
                route1_rate: route1.base_rate,
                route2_rate: route2.base_rate,
                total_rate: route1.base_rate + route2.base_rate,
                route1_valid_from: route1.valid_from,
                route1_valid_to: route1.valid_to,
                route2_valid_from: route2.valid_from,
                route2_valid_to: route2.valid_to
            }}
            LIMIT 20
            """
            
            bind_vars = {
                "origin": origin_port,
                "destination": destination_port,
                "org_id": organization_id
            }
            
            if valid_date:
                bind_vars["valid_date"] = valid_date.isoformat()
            
            cursor = self.db.aql.execute(aql, bind_vars=bind_vars)
            
            alternatives = [doc for doc in cursor]
            # Sort by total rate (ascending)
            alternatives.sort(key=lambda x: x.get("total_rate", float('inf')))
            return alternatives[:20]
            
        except Exception as e:
            logger.error(f"Error finding alternative routes: {e}")
            return []
