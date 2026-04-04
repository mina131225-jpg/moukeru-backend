import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.post_likes import Post_likes

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Post_likesService:
    """Service layer for Post_likes operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Post_likes]:
        """Create a new post_likes"""
        try:
            obj = Post_likes(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created post_likes with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating post_likes: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Post_likes]:
        """Get post_likes by ID"""
        try:
            query = select(Post_likes).where(Post_likes.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching post_likes {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of post_likess"""
        try:
            query = select(Post_likes)
            count_query = select(func.count(Post_likes.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Post_likes, field):
                        query = query.where(getattr(Post_likes, field) == value)
                        count_query = count_query.where(getattr(Post_likes, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Post_likes, field_name):
                        query = query.order_by(getattr(Post_likes, field_name).desc())
                else:
                    if hasattr(Post_likes, sort):
                        query = query.order_by(getattr(Post_likes, sort))
            else:
                query = query.order_by(Post_likes.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching post_likes list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Post_likes]:
        """Update post_likes"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Post_likes {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated post_likes {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating post_likes {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete post_likes"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Post_likes {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted post_likes {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting post_likes {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Post_likes]:
        """Get post_likes by any field"""
        try:
            if not hasattr(Post_likes, field_name):
                raise ValueError(f"Field {field_name} does not exist on Post_likes")
            result = await self.db.execute(
                select(Post_likes).where(getattr(Post_likes, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching post_likes by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Post_likes]:
        """Get list of post_likess filtered by field"""
        try:
            if not hasattr(Post_likes, field_name):
                raise ValueError(f"Field {field_name} does not exist on Post_likes")
            result = await self.db.execute(
                select(Post_likes)
                .where(getattr(Post_likes, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Post_likes.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching post_likess by {field_name}: {str(e)}")
            raise