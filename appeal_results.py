import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.appeal_results import Appeal_results

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Appeal_resultsService:
    """Service layer for Appeal_results operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Appeal_results]:
        """Create a new appeal_results"""
        try:
            obj = Appeal_results(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created appeal_results with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating appeal_results: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Appeal_results]:
        """Get appeal_results by ID"""
        try:
            query = select(Appeal_results).where(Appeal_results.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching appeal_results {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of appeal_resultss"""
        try:
            query = select(Appeal_results)
            count_query = select(func.count(Appeal_results.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Appeal_results, field):
                        query = query.where(getattr(Appeal_results, field) == value)
                        count_query = count_query.where(getattr(Appeal_results, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Appeal_results, field_name):
                        query = query.order_by(getattr(Appeal_results, field_name).desc())
                else:
                    if hasattr(Appeal_results, sort):
                        query = query.order_by(getattr(Appeal_results, sort))
            else:
                query = query.order_by(Appeal_results.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching appeal_results list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Appeal_results]:
        """Update appeal_results"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Appeal_results {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated appeal_results {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating appeal_results {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete appeal_results"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Appeal_results {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted appeal_results {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting appeal_results {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Appeal_results]:
        """Get appeal_results by any field"""
        try:
            if not hasattr(Appeal_results, field_name):
                raise ValueError(f"Field {field_name} does not exist on Appeal_results")
            result = await self.db.execute(
                select(Appeal_results).where(getattr(Appeal_results, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching appeal_results by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Appeal_results]:
        """Get list of appeal_resultss filtered by field"""
        try:
            if not hasattr(Appeal_results, field_name):
                raise ValueError(f"Field {field_name} does not exist on Appeal_results")
            result = await self.db.execute(
                select(Appeal_results)
                .where(getattr(Appeal_results, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Appeal_results.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching appeal_resultss by {field_name}: {str(e)}")
            raise